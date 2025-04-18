# pm/core/background_tasks.py
from PySide6.QtCore import QObject, Signal, Slot, QThread, Qt # Added Slot, QThread
from loguru import logger
from pathlib import Path
import time
import re
import json # For parsing critic output
from typing import List, Dict, Optional, Any

from .token_utils import count_tokens
from . import rag_service
from .gemini_service import GeminiService
from .ollama_service import OllamaService
from .project_config import DEFAULT_CONFIG, get_effective_prompt # Use prompt getter

RESERVE_FOR_IO = 1024
MAX_CRITIC_LOOPS = 3 # Maximum revisions by critic

class Worker(QObject):
    """
    Performs context gathering and LLM streaming in a separate thread.
    Includes Plan-Critic-Executor workflow and direct execution mode.
    Designed to be moved to a QThread. Includes interrupt handling.
    """
    status_update = Signal(str)
    context_info = Signal(int, int)  # used_tokens, max_tokens
    stream_chunk = Signal(str)       # Final executor output chunk
    stream_error = Signal(str)
    stream_finished = Signal()       # Indicates normal or stopped completion

    # Optional signals for intermediate workflow steps
    plan_generated = Signal(list)
    plan_critiqued = Signal(dict)
    plan_accepted = Signal(list)

    def __init__(self,
                 settings: dict,
                 history: list,
                 main_services: dict,
                 checked_file_paths: List[Path],
                 project_path: Path,
                 disable_critic: bool): # <<< ADDED disable_critic flag <<<
        super().__init__()
        self.settings = settings
        self.history = history
        self.model_service: Optional[OllamaService | GeminiService] = main_services.get('model_service')
        self.summarizer_service: Optional[OllamaService | GeminiService] = main_services.get('summarizer_service')
        self.checked_file_paths = checked_file_paths
        self.project_path = project_path
        self.disable_critic_workflow = disable_critic # <<< STORE FLAG <<<
        self._current_thread : Optional[QThread] = None
        self._interruption_requested_flag = False # Internal flag
        logger.debug(f"Worker initialized (Critic Disabled: {self.disable_critic_workflow}).")

    def assign_thread(self, thread: QThread):
        """Stores a reference to the thread this worker will run on."""
        logger.debug(f"Worker: Assigning thread {thread.objectName()}")
        self._current_thread = thread

    @Slot()
    def request_interruption(self):
        """Sets the internal interruption flag."""
        logger.debug("Worker: Interruption flag set.")
        self._interruption_requested_flag = True

    def _is_interruption_requested(self) -> bool:
        """Checks the internal flag and the owning thread's request."""
        if self._interruption_requested_flag:
            return True
        thread_to_check = self._current_thread if self._current_thread else QThread.currentThread()
        return thread_to_check and thread_to_check.isInterruptionRequested()

    def _gather_context(self, max_tokens: int) -> tuple[dict, int, int]:
        """Gathers all context types based on settings and checked files."""
        logger.debug("Worker: Starting context gathering.")
        total_context_tokens = 0
        # Reserve tokens for input/output formatting and potential LLM overhead
        available_tokens = max(0, max_tokens - RESERVE_FOR_IO - 500)
        context_parts = {'code': [], 'local': [], 'remote': []}
        original_query = ""
        chat_history_str = ""

        # --- Extract User Query and Format History ---
        # Find latest user query
        for i in range(len(self.history) - 1, -1, -1):
             if self.history[i].get('role') == 'user':
                  original_query = self.history[i].get('content', '').strip()
                  break
        if not original_query:
             logger.error("Worker: Could not find user query in history.")
             raise ValueError("User query not found in history snapshot.")

        # Format history string (excluding last user query for context)
        history_str_parts = []
        last_user_idx = -1
        for i in range(len(self.history) - 1, -1, -1):
             if self.history[i].get('role') == 'user':
                  last_user_idx = i
                  break
        # Include messages up to (but not including) the last user message
        limit = last_user_idx if last_user_idx != -1 else len(self.history)
        for msg in self.history[:limit]:
             role = msg.get('role', 'System').capitalize()
             content = msg.get('content', '').strip()
             if content:
                  history_str_parts.append(f"{role}:\n{content}")
        chat_history_str = "\n---\n".join(history_str_parts) if history_str_parts else "[No previous conversation]"
        # --------------------------------------------

        if self._is_interruption_requested(): return {}, 0, 0 # Check early

        # --- Summarize for RAG if needed ---
        search_query = original_query
        summarizer_enabled = self.settings.get('rag_summarizer_enabled', False)
        # Determine if any external source requiring summarization is enabled
        external_rag_will_run = (
            self.settings.get('rag_external_enabled', False) or
            self.settings.get('rag_google_enabled', False) or
            self.settings.get('rag_bing_enabled', False) or
            self.settings.get('rag_stackexchange_enabled', False) or
            self.settings.get('rag_github_enabled', False) or
            self.settings.get('rag_arxiv_enabled', False)
        )
        if summarizer_enabled and external_rag_will_run and self.summarizer_service:
             self.status_update.emit("Summarizing query for RAG...")
             search_query = self._summarize_query(original_query) # Pass only the query
             if self._is_interruption_requested(): return {}, 0, 0
        # ------------------------------------

        # --- Gather RAG Contexts ---
        if external_rag_will_run and available_tokens > 0:
            self.status_update.emit("Fetching external RAG sources...")
            parts, tokens = self._gather_external_rag_context(search_query, available_tokens)
            if parts: context_parts['remote'] = parts
            available_tokens = max(0, available_tokens - tokens)
            total_context_tokens += tokens
            logger.info(f"External RAG used {tokens} tokens. Available: {available_tokens}")
            if self._is_interruption_requested(): return {}, 0, 0
        else:
            logger.debug("Skipping external RAG fetch (disabled or no tokens).")

        if self.settings.get('rag_local_enabled', False) and available_tokens > 0:
            self.status_update.emit("Fetching local RAG sources...")
            parts, tokens = self._gather_local_rag_context(available_tokens)
            if parts: context_parts['local'] = parts
            available_tokens = max(0, available_tokens - tokens)
            total_context_tokens += tokens
            logger.info(f"Local RAG sources used {tokens} tokens. Available: {available_tokens}")
            if self._is_interruption_requested(): return {}, 0, 0
        else:
            logger.debug("Skipping local RAG sources fetch (disabled or no tokens).")
        # ----------------------------

        # --- Gather Checked File Context ---
        if self.checked_file_paths and available_tokens > 0:
             self.status_update.emit("Gathering checked file context...")
             parts, tokens = self._gather_tree_context(available_tokens)
             if parts: context_parts['code'] = parts
             available_tokens = max(0, available_tokens - tokens)
             total_context_tokens += tokens
             logger.info(f"Checked file context used {tokens} tokens. Available: {available_tokens}")
             if self._is_interruption_requested(): return {}, 0, 0
        elif self.checked_file_paths:
             logger.debug("Skipping checked file context (no tokens available).")
        else:
             logger.debug("Skipping checked file context (no files checked).")
        # -------------------------------

        logger.info(f"Worker: Context gathering complete. Total tokens used for context: {total_context_tokens}")

        # Combine into final context dictionary for prompt formatting
        final_context = {
            'query': original_query,
            'code_context': "\n".join(context_parts.get('code', [])).strip() or "[No relevant code context provided]",
            'chat_history': chat_history_str,
            'rag_context': "\n\n".join(context_parts.get('remote', [])).strip() or "[No relevant external context provided]",
            'local_context': "\n\n".join(context_parts.get('local', [])).strip() or "[No relevant local context provided]",
            # Add other placeholders if needed by prompts
        }

        # Emit final token counts
        self.context_info.emit(total_context_tokens, max_tokens)
        return final_context, total_context_tokens, max_tokens


    # --- Context Gathering Helpers (with interruption checks) ---
    def _gather_tree_context(self, available_tokens: int) -> tuple[List[str], int]:
        """Gathers context from files checked in the file tree."""
        parts: List[str] = []
        tokens_used: int = 0
        files_processed: int = 0
        project_path: Path = self.project_path
        logger.debug(f"Worker: Gathering Tree context for {len(self.checked_file_paths)} files (Budget: {available_tokens}).")

        if not self.checked_file_paths:
             return [], 0

        for path in self.checked_file_paths:
            if self._is_interruption_requested():
                logger.info("Worker: Stop requested during Tree context.")
                break # <<< CHECK

            if available_tokens <= 0:
                logger.info("Worker: Token budget reached during Tree context.")
                break

            if not path.is_file():
                # Log skipped non-files if needed, but avoid clutter
                # logger.trace(f"Skipping non-file item in tree context: {path}")
                continue

            try:
                # Basic size check before reading? Might save time on huge files.
                # file_size = path.stat().st_size
                # if file_size > 5 * 1024 * 1024: # Example limit
                #     logger.warning(f"Skipping very large file in tree context: {path.name}")
                #     continue

                text = path.read_text(encoding='utf-8', errors='ignore')
                if not text.strip(): # Skip empty files
                    logger.trace(f"Skipping empty file in tree context: {path.name}")
                    continue

                # Determine relative path for markers
                try:
                    relative_path_str = str(path.relative_to(project_path))
                except ValueError:
                    relative_path_str = path.name # Fallback if not under project root

                # Use File markers for context
                header = f'### START FILE: {relative_path_str} ###'
                footer = f'### END FILE: {relative_path_str} ###'
                header_tok = count_tokens(header) + 1 # Approx newline token
                snippet_tok = count_tokens(text)
                footer_tok = count_tokens(footer) + 1 # Approx newline token
                total_tok = header_tok + snippet_tok + footer_tok

                if snippet_tok <= 0: continue # Skip if content has no tokens

                if total_tok <= available_tokens:
                    # Add full content
                    parts.append(f'{header}\n{text}\n{footer}')
                    available_tokens -= total_tok
                    tokens_used += total_tok
                    files_processed += 1
                else:
                    # Try to truncate
                    needed_snippet_tokens = max(0, available_tokens - header_tok - footer_tok - 5) # -5 for safety
                    if needed_snippet_tokens > 5: # Only truncate if we can fit a small amount
                        ratio = needed_snippet_tokens / snippet_tok if snippet_tok > 0 else 0
                        # Estimate character cutoff based on token ratio
                        cutoff = int(len(text) * ratio)
                        truncated_text = text[:cutoff].strip()
                        # Recalculate tokens for the truncated part
                        tok = count_tokens(truncated_text)
                        final_total_tok = header_tok + tok + footer_tok

                        if tok > 0 and final_total_tok <= available_tokens:
                             parts.append(f'{header}\n{truncated_text}\n{footer}')
                             available_tokens -= final_total_tok
                             tokens_used += final_total_tok
                             files_processed += 1
                             logger.warning(f'Worker: Truncated Tree file {relative_path_str} ({tok} snippet tokens). Rem: {available_tokens}')
                        else:
                             # Even truncated version doesn't fit
                             logger.warning(f"Could not fit even truncated content for {relative_path_str}. Skipping.")
                             break # Stop processing further files if budget is too tight
                    else:
                         # Not enough space even for header/footer and minimal snippet
                         logger.warning(f"Not enough token budget ({available_tokens}) to include even truncated header/footer for {relative_path_str}. Skipping.")
                         break # Stop processing further files

            except OSError as e:
                logger.warning(f"Worker: OS Error reading Tree file {path}: {e}")
            except Exception as e:
                logger.warning(f"Worker: Failed to process Tree file {path}: {e}")

        logger.info(f"Worker: Tree context complete. Added {files_processed} files. Tokens used by tree: {tokens_used}.")
        return parts, tokens_used

    def _summarize_query(self, original_query: str) -> str:
        """Summarizes the query using the configured summarizer service."""
        search_query = original_query if original_query is not None else ""
        if not self.summarizer_service:
            logger.warning("Worker: Summarizer service not available, skipping query summarization.")
            return search_query

        if self._is_interruption_requested():
            logger.info("Worker interrupted before query summarization.")
            return search_query # <<< CHECK

        logger.debug(f"Worker: Attempting query summarization...")
        # Format history for summarizer (might be simpler than main context)
        # For now, let's omit history to keep it simple, adjust if needed
        placeholders = {'current_query': original_query, 'chat_history': "[History not used in this version]"}
        try:
            # Use the prompt getter function
            prompt = get_effective_prompt(self.settings, 'rag_summarizer_prompt_template', placeholders)
            if not prompt:
                 logger.error("Worker: Failed to format RAG summarizer prompt.")
                 return search_query # Return original on format error

            response = self.summarizer_service.send(prompt) # Use non-streaming for summarizer
            if response is not None:
                summarized = response.strip()
                if summarized:
                    search_query = summarized
                    logger.info(f'Worker: Summarized query: "{search_query}"')
                else:
                    logger.warning("Worker: Summarizer returned empty response.")
            else:
                logger.warning("Worker: Summarizer returned None response.")
        except Exception as e:
            logger.error(f"Worker: Query summarization failed: {e}.")
            self.stream_error.emit(f"Summarization failed: {e}")
            search_query = original_query # Fallback

        return search_query if search_query is not None else ""

    def _gather_external_rag_context(self, search_query: str, available_tokens: int) -> tuple[List[str], int]:
        """Gathers context from enabled external RAG sources."""
        parts: List[str] = []
        tokens_used: int = 0
        # Get settings for max results
        max_results_per_source: int = self.settings.get('rag_max_results_per_source', 3)
        max_ranked_results_to_use: int = self.settings.get('rag_max_ranked_results', 5)

        logger.debug(f"Worker: Gathering External RAG (Budget: {available_tokens}). Query: '{search_query[:50]}...'")
        try:
            if self._is_interruption_requested():
                logger.info("Worker: Stop requested before external RAG fetch.")
                return [], 0 # <<< CHECK

            fetched_results = rag_service.fetch_external_sources_parallel(
                search_query=search_query,
                settings=self.settings,
                max_results_per_source=max_results_per_source
            )

            if self._is_interruption_requested():
                logger.info("Worker: Stop requested after external RAG fetch.")
                return [], 0 # <<< CHECK

            if not fetched_results:
                logger.info("Worker: No raw results from external sources.")
                return [], 0

            if self._is_interruption_requested():
                logger.info("Worker: Stop requested before external RAG ranking.")
                return [], 0 # <<< CHECK

            # Filter and rank results
            ranked_results = rag_service.filter_and_rank_results(
                results=fetched_results,
                query=search_query,
                max_results_to_return=max_ranked_results_to_use, # Pass limit here
                settings=self.settings
            )

            if self._is_interruption_requested():
                logger.info("Worker: Stop requested after external RAG ranking.")
                return [], 0 # <<< CHECK

            if not ranked_results:
                logger.info("Worker: No external results passed ranking.")
                return [], 0

            logger.debug(f"Worker: Processing {len(ranked_results)} ranked external results...")
            for result in ranked_results:
                if self._is_interruption_requested():
                    logger.info("Worker: Stop requested during External RAG formatting.")
                    break # <<< CHECK

                if available_tokens <= 0:
                    logger.info("Worker: Token budget reached during Ext RAG formatting.")
                    break

                # Extract data safely using .get()
                source = result.get('source','Web').capitalize()
                title = result.get('title','N/A')
                url = result.get('url','')
                snippet = result.get('text_snippet','').strip()

                if snippet:
                    header=f'### External RAG: {source} - {title} ({url}) ###'
                    footer='### End External RAG ###'
                    h_tok=count_tokens(header); s_tok=count_tokens(snippet); f_tok=count_tokens(footer); total=h_tok+s_tok+f_tok

                    if s_tok <= 0: continue # Skip empty snippets

                    if total <= available_tokens:
                        parts.append(f'{header}\n{snippet}\n{footer}')
                        available_tokens -= total
                        tokens_used += total
                        logger.trace(f"Worker: Added Ext RAG '{title[:30]}' ({total} tokens). Rem: {available_tokens}")
                    else:
                        # Try truncating
                        needed=max(0, available_tokens - h_tok - f_tok - 10) # Safety margin
                        if needed > 0:
                            ratio = needed/s_tok if s_tok else 0
                            cutoff=int(len(snippet)*ratio)
                            trunc=snippet[:cutoff].strip()
                            tok=count_tokens(trunc)
                            final_total=h_tok+tok+f_tok
                            if tok>0 and final_total<=available_tokens:
                                parts.append(f'{header}\n{trunc}\n{footer}')
                                available_tokens -= final_total
                                tokens_used += final_total
                                logger.warning(f'Worker: Truncated Ext RAG "{title[:30]}" ({tok} snippet tokens). Rem: {available_tokens}')
                            else:
                                logger.warning(f"Could not fit even truncated Ext RAG for {title[:30]}. Skipping.")
                                break # Stop processing if budget tight
                        else:
                             logger.warning(f"Not enough token budget ({available_tokens}) for Ext RAG header/footer {title[:30]}. Skipping.")
                             break # Stop processing

        except Exception as e:
             logger.exception("Worker: Error during External RAG fetching/processing")
             self.stream_error.emit(f"External RAG Error: {e}")

        logger.info(f"Worker: External RAG complete. Added {len(parts)} results. Tokens used here: {tokens_used}.")
        return parts, tokens_used

    def _gather_local_rag_context(self, available_tokens: int) -> tuple[List[str], int]:
        """Gathers context from explicitly listed local RAG sources in settings."""
        parts: List[str] = []
        tokens_used: int = 0
        sources_processed: int = 0
        local_rag_sources = self.settings.get('rag_local_sources', []) # This is a list of dicts

        logger.debug(f"Worker: Gathering Local RAG for {len(local_rag_sources)} sources (Budget: {available_tokens})...")
        if not local_rag_sources:
             return [], 0

        for source_info in local_rag_sources:
            if self._is_interruption_requested():
                logger.info("Worker: Stop requested during Local RAG gathering.")
                break # <<< CHECK

            if available_tokens <= 0:
                logger.info("Worker: Token budget reached during Local RAG gathering.")
                break

            # Check if source is enabled and has a path
            if source_info.get('enabled', False):
                path_str = source_info.get('path')
                if not path_str:
                     logger.warning("Worker: Skipping Local RAG source with no path.")
                     continue

                try:
                    path = Path(path_str).resolve()
                    if path.is_file():
                        try:
                            if self._is_interruption_requested(): break # <<< CHECK

                            text = path.read_text(encoding='utf-8', errors='ignore')
                            if not text.strip():
                                logger.trace(f"Worker: Skipping empty Local RAG file: {path.name}")
                                continue

                            # Use path_str from config for markers for clarity
                            header = f'### Local RAG File: {path_str} ###'
                            footer = '### End Local RAG File ###'
                            h_tok=count_tokens(header); s_tok=count_tokens(text); f_tok=count_tokens(footer); total = h_tok + s_tok + f_tok

                            if s_tok <= 0: continue

                            if total <= available_tokens:
                                parts.append(f'{header}\n{text}\n{footer}')
                                available_tokens -= total
                                tokens_used += total
                                sources_processed += 1
                                logger.trace(f"Worker: Added Local RAG file '{path.name}' ({total} tokens). Rem: {available_tokens}")
                            else:
                                # Try truncating
                                needed = max(0, available_tokens - h_tok - f_tok - 10)
                                if needed > 0:
                                    ratio = needed / s_tok if s_tok else 0
                                    cutoff = int(len(text) * ratio)
                                    trunc = text[:cutoff].strip()
                                    tok = count_tokens(trunc)
                                    final_total = h_tok + tok + f_tok
                                    if tok > 0 and final_total <= available_tokens:
                                        parts.append(f'{header}\n{trunc}\n{footer}')
                                        available_tokens -= final_total
                                        tokens_used += final_total
                                        sources_processed += 1
                                        logger.warning(f'Worker: Truncated Local RAG file {path.name} ({tok} snippet tokens). Rem: {available_tokens}')
                                    else:
                                        logger.warning(f"Could not fit even truncated Local RAG for {path.name}. Skipping.")
                                        break # Stop processing
                                else:
                                     logger.warning(f"Not enough token budget ({available_tokens}) for Local RAG header/footer {path.name}. Skipping.")
                                     break # Stop processing
                        except OSError as e:
                            logger.warning(f"Worker: OS Error reading Local RAG file {path}: {e}")
                        except Exception as e:
                            logger.warning(f"Worker: Error processing Local RAG file {path}: {e}")
                    elif path.is_dir():
                        # Directory processing is not implemented here, handled by tree context if checked
                        logger.trace(f"Worker: Skipping directory Local RAG source '{path_str}' (handled by tree context if checked).")
                    else:
                        logger.warning(f"Worker: Local RAG source path not valid file/dir: {path_str}")
                except Exception as e:
                    # Error resolving path or other unexpected issue
                    logger.warning(f"Task: Failed to process Local RAG source '{path_str}': {e}")
            else:
                 # Source is not enabled
                 logger.trace(f"Worker: Skipping disabled Local RAG source: {source_info.get('path', 'N/A')}")

        logger.info(f"Worker: Local RAG complete. Processed {sources_processed} enabled sources. Tokens used here: {tokens_used}.")
        return parts, tokens_used

    def _call_llm(self, prompt: str, use_stream: bool = False):
        """Helper to call the main LLM service, handling stream/non-stream."""
        if not self.model_service:
            raise ValueError("LLM model service is not available.")
        if use_stream:
            return self.model_service.stream(prompt)
        else:
            return self.model_service.send(prompt)

    # --- Main Processing Method (Slot) ---
    @Slot()
    def process(self):
        logger.info("Worker process started.")
        stream_interrupted = False # Flag to track if stop happened during stream
        final_plan = [] # Stores the plan that will eventually be executed

        try:
            # 1. Gather Context (Common Step)
            if self._is_interruption_requested(): logger.info("Worker interrupted before context gathering."); return
            self.status_update.emit("Gathering context...")
            max_limit = self.settings.get('context_limit', DEFAULT_CONFIG['context_limit'])
            context_data, context_tokens, max_tokens = self._gather_context(max_limit)
            if self._is_interruption_requested(): logger.info("Worker interrupted after context gathering."); return


            # 2. Check Workflow Path
            if self.disable_critic_workflow:
                # --- Direct Execution Path ---
                logger.info("Worker: Running DIRECT EXECUTION workflow.")
                self.status_update.emit("Preparing direct execution prompt...")
                direct_executor_prompt = get_effective_prompt(self.settings, 'direct_executor_prompt_template', context_data)
                if not direct_executor_prompt: raise ValueError("Failed to format direct executor prompt.")

                final_prompt_tokens = count_tokens(direct_executor_prompt)
                logger.info(f"Direct Execution prompt tokens: {final_prompt_tokens} / {max_tokens}")
                if final_prompt_tokens > max_tokens: logger.warning(f"Direct Execution prompt ({final_prompt_tokens} tokens) exceeds limit ({max_tokens}).")

                if self._is_interruption_requested(): logger.info("Worker interrupted before direct execution."); return
                self.status_update.emit("Executing directly...")
                logger.debug("Worker: Starting Direct Executor stream...")

                stream_generator = self._call_llm(direct_executor_prompt, use_stream=True)
                for chunk in stream_generator:
                    if self._is_interruption_requested(): stream_interrupted = True; break
                    self.stream_chunk.emit(chunk)
                # --- End Direct Execution Path ---

            else:
                # --- Plan-Critic-Executor Path ---
                logger.info("Worker: Running PLAN-CRITIC-EXECUTOR workflow.")

                # a. Call Planner
                self.status_update.emit("Generating execution plan...")
                planner_prompt = get_effective_prompt(self.settings, 'planner_prompt_template', context_data)
                if not planner_prompt: raise ValueError("Failed to format planner prompt.")
                if self._is_interruption_requested(): logger.info("Worker interrupted before planner call."); return

                planner_response = self._call_llm(planner_prompt, use_stream=False)
                if self._is_interruption_requested(): logger.info("Worker interrupted after planner call."); return

                # Parse plan (simple newline split for now)
                proposed_plan = [line.strip() for line in planner_response.strip().split('\n') if line.strip()]
                logger.info(f"Worker: Proposed plan received:\n{proposed_plan}")
                self.plan_generated.emit(proposed_plan) # Optional signal

                # b. Critic Loop (MODIFIED LOGIC for RETRY)
                current_plan = proposed_plan
                final_plan = proposed_plan # Default to initial plan if loop finishes without acceptance
                loop_count = 0
                plan_accepted_by_critic = False # Flag to track if critic explicitly said GOOD

                while loop_count < MAX_CRITIC_LOOPS:
                    if self._is_interruption_requested(): logger.info("Worker interrupted during critic loop."); return
                    self.status_update.emit(f"Critiquing plan (Attempt {loop_count + 1}/{MAX_CRITIC_LOOPS})...")

                    critic_context = context_data.copy()
                    # Format plan for prompt (numbered list string)
                    critic_context['proposed_plan'] = "\n".join(f"{i+1}. {step}" for i, step in enumerate(current_plan))
                    critic_prompt = get_effective_prompt(self.settings, 'critic_prompt_template', critic_context)
                    if not critic_prompt: raise ValueError("Failed to format critic prompt.")

                    critic_response_str = self._call_llm(critic_prompt, use_stream=False)
                    if self._is_interruption_requested(): logger.info("Worker interrupted after critic call."); return

                    # --- Modified JSON Parsing and Loop Control ---
                    critic_response_valid = False # Assume invalid initially
                    critic_data = None

                    try:
                        # Find JSON block in response
                        json_match = re.search(r'```json\s*(\{.*?\})\s*```', critic_response_str, re.DOTALL | re.IGNORECASE)
                        if not json_match:
                             # Fallback: Assume the whole response is JSON if no markdown found
                             json_match = re.search(r'^(\{.*?\})$', critic_response_str.strip(), re.DOTALL)

                        if json_match:
                             critic_response_json = json_match.group(1)
                             critic_data = json.loads(critic_response_json)
                             logger.debug(f"Worker: Critic JSON response parsed: {critic_data}")
                             self.plan_critiqued.emit(critic_data) # Optional signal
                             critic_response_valid = True # Mark as valid JSON
                        else:
                             # Keep critic_response_valid as False
                             logger.error(f"Worker: Critic response did not contain expected JSON block (Loop {loop_count+1}). Response:\n{critic_response_str}")
                             # Will retry if loops remain

                    except json.JSONDecodeError as e:
                         # Keep critic_response_valid as False
                         logger.error(f"Worker: Failed to parse critic JSON response (Loop {loop_count+1}): {e}. Response:\n{critic_response_str}")
                         # Will retry if loops remain
                    except Exception as e:
                         # Keep critic_response_valid as False
                         logger.exception(f"Worker: Unexpected error processing critic response (Loop {loop_count+1}): {e}")
                         # Will retry if loops remain


                    # --- Process Valid Critic Response ---
                    if critic_response_valid and critic_data:
                        plan_status = critic_data.get('plan_status')
                        critique_reasoning = critic_data.get('critique_reasoning', 'N/A')
                        revised_plan = critic_data.get('revised_plan') # Should be list

                        if plan_status == 'GOOD':
                            logger.info(f"Worker: Plan accepted by critic (Loop {loop_count+1}). Reason: {critique_reasoning}")
                            final_plan = current_plan # The plan submitted was good
                            plan_accepted_by_critic = True
                            self.plan_accepted.emit(final_plan) # Optional signal
                            break # <<< EXIT LOOP: Plan is good

                        elif plan_status == 'BAD':
                            logger.warning(f"Worker: Plan rejected by critic (Loop {loop_count+1}). Reason: {critique_reasoning}")
                            if revised_plan and isinstance(revised_plan, list) and revised_plan:
                                logger.info(f"Worker: Critic provided revised plan:\n{revised_plan}")
                                current_plan = revised_plan # Use the revision for the next loop iteration
                                # Do not break, continue to next loop iteration
                            else:
                                logger.error("Worker: Critic rejected plan but provided no valid revision. Using last plan and exiting loop.")
                                final_plan = current_plan # Use the plan that was just rejected
                                break # <<< EXIT LOOP: Critic failed to revise
                        else:
                            logger.error(f"Worker: Critic returned unexpected status '{plan_status}' (Loop {loop_count+1}). Using current plan and exiting loop.")
                            final_plan = current_plan
                            break # <<< EXIT LOOP: Unexpected status

                    # --- Increment Loop Count ---
                    # Happens if:
                    # 1. JSON was invalid/parsing failed
                    # 2. Plan status was BAD and a valid revision was provided
                    loop_count += 1
                    # Wait a tiny bit before retrying on parse failure? Optional.
                    # if not critic_response_valid: time.sleep(0.1)

                # --- End of while loop ---
                if not plan_accepted_by_critic: # If loop finished without explicit acceptance
                    logger.warning(f"Worker: Critic loop finished after {loop_count} attempts without plan acceptance. Using last evaluated plan.")
                    # final_plan already holds the last value of current_plan
                    self.plan_accepted.emit(final_plan) # Emit the plan we're using

                # c. Call Executor (using final_plan)
                self.status_update.emit("Executing final plan...")
                executor_context = context_data.copy()
                # Format final plan for prompt
                executor_context['final_plan'] = "\n".join(f"{i+1}. {step}" for i, step in enumerate(final_plan))
                executor_prompt = get_effective_prompt(self.settings, 'executor_prompt_template', executor_context)
                if not executor_prompt: raise ValueError("Failed to format executor prompt.")

                final_prompt_tokens = count_tokens(executor_prompt)
                logger.info(f"Executor prompt tokens: {final_prompt_tokens} / {max_tokens}")
                if final_prompt_tokens > max_tokens: logger.warning(f"Executor prompt ({final_prompt_tokens} tokens) exceeds limit ({max_tokens}).")

                if self._is_interruption_requested(): logger.info("Worker interrupted before executor call."); return
                logger.debug("Worker: Starting Executor stream...")

                stream_generator = self._call_llm(executor_prompt, use_stream=True)
                for chunk in stream_generator:
                    if self._is_interruption_requested(): stream_interrupted = True; break
                    self.stream_chunk.emit(chunk)
                # --- End Plan-Critic-Executor Path ---

            # 3. Final Logging
            if stream_interrupted:
                 logger.info("Worker: Stream finished due to interruption request.")
            else:
                 logger.info("Worker: Stream finished normally.")

        except Exception as e:
            logger.exception("Error occurred in worker process:")
            if not self._is_interruption_requested():
                 self.stream_error.emit(f"Worker Error: {type(e).__name__}: {e}")
            else:
                 logger.info(f"Worker error likely due to interruption request: {e}")
        finally:
            # Ensure finished signal is always emitted
            logger.debug("Worker: Emitting finished signal from finally block.")
            self.stream_finished.emit() # Emit to signal completion/cleanup needed