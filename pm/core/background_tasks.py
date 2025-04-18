# pm/core/background_tasks.py
from PySide6.QtCore import QObject, Signal, Slot, QThread, Qt # Added Slot, QThread
from loguru import logger
from pathlib import Path
import time
import re
from typing import List, Dict, Optional, Any

from .token_utils import count_tokens
from . import rag_service
from .gemini_service import GeminiService
from .ollama_service import OllamaService
from .project_config import DEFAULT_CONFIG, DEFAULT_PROMPT_TEMPLATE # For fallback template

RESERVE_FOR_IO = 1024

class Worker(QObject):
    """
    Performs context gathering and LLM streaming in a separate thread.
    Designed to be moved to a QThread. Includes interrupt handling.
    """
    # --- Signals (Defined directly in the class) ---
    status_update = Signal(str)
    context_info = Signal(int, int)  # used_tokens, max_tokens
    stream_chunk = Signal(str)
    stream_error = Signal(str)
    stream_finished = Signal()       # Indicates normal or stopped completion

    def __init__(self,
                 settings: dict,
                 history: list,
                 main_services: dict,
                 checked_file_paths: List[Path],
                 project_path: Path):
        super().__init__()
        self.settings = settings
        self.history = history
        self.model_service: Optional[OllamaService | GeminiService] = main_services.get('model_service')
        self.summarizer_service: Optional[OllamaService | GeminiService] = main_services.get('summarizer_service')
        self.checked_file_paths = checked_file_paths
        self.project_path = project_path
        self._current_thread : Optional[QThread] = None # To check interruption
        logger.debug("Worker initialized.")

    def _is_interruption_requested(self) -> bool:
        """Checks if the owning thread has requested interruption."""
        if self._current_thread is None:
            self._current_thread = QThread.currentThread()
            # if self._current_thread: logger.debug(f"Worker running in thread: {self._current_thread.objectName()} ({self._current_thread})")
            # else: logger.warning("Worker could not get current thread reference."); return False # Be less verbose
        return self._current_thread and self._current_thread.isInterruptionRequested()


    # --- Helper Methods for Context Gathering ---
    def _gather_tree_context(self, available_tokens: int) -> tuple[List[str], int]:
        parts: List[str] = []; tokens_used: int = 0; files_processed: int = 0
        project_path: Path = self.project_path
        logger.debug(f"Worker: Gathering Tree context for {len(self.checked_file_paths)} files (Budget: {available_tokens})...")
        if not self.checked_file_paths: return [], 0
        for path in self.checked_file_paths:
            if self._is_interruption_requested(): logger.info("Worker: Stop requested during Tree context gathering."); break
            if available_tokens <= 0: logger.info("Worker: Token budget reached during Tree context gathering."); break
            if not path.is_file(): continue
            try:
                text = path.read_text(encoding='utf-8', errors='ignore');
                if not text: continue
                try: relative_path_str = str(path.relative_to(project_path))
                except ValueError: relative_path_str = path.name
                header = f'### File: {relative_path_str} ###'; footer = '### End File ###'
                header_tok = count_tokens(header); snippet_tok = count_tokens(text); footer_tok = count_tokens(footer); total_tok = header_tok + snippet_tok + footer_tok
                if snippet_tok <= 0: continue
                if total_tok <= available_tokens: parts.append(f'{header}\n{text}\n{footer}'); available_tokens -= total_tok; tokens_used += total_tok; files_processed += 1
                else:
                    needed_snippet_tokens = max(0, available_tokens - header_tok - footer_tok - 10)
                    if needed_snippet_tokens > 0:
                        ratio = needed_snippet_tokens / snippet_tok if snippet_tok > 0 else 0; cutoff = int(len(text) * ratio); truncated_text = text[:cutoff]; tok = count_tokens(truncated_text); final_total_tok = header_tok + tok + footer_tok
                        if tok > 0 and final_total_tok <= available_tokens: parts.append(f'{header}\n{truncated_text}\n{footer}'); available_tokens -= final_total_tok; tokens_used += final_total_tok; files_processed += 1; logger.warning(f'Worker: Truncated Tree file {path.name} ({tok} snippet tokens). Rem: {available_tokens}')
            except OSError as e: logger.warning(f"Worker: OS Error reading Tree file {path}: {e}")
            except Exception as e: logger.warning(f"Worker: Failed to process Tree file {path}: {e}")
        logger.info(f"Worker: Tree context complete. Added {files_processed} files. Tokens used by tree: {tokens_used}.")
        return parts, tokens_used

    def _summarize_query(self, original_query: str) -> str:
        """Summarizes the query using the summarizer LLM if enabled/available."""
        search_query = original_query if original_query is not None else ""
        summarizer_enabled = self.settings.get('rag_summarizer_enabled', False); summarizer_available = self.summarizer_service is not None; can_summarize = summarizer_enabled and summarizer_available and original_query
        if can_summarize:
            if self._is_interruption_requested(): return search_query
            self.status_update.emit("Summarizing query..."); logger.debug(f"Worker: Attempting query summarization...")
            prompt_template = self.settings.get('rag_summarizer_prompt_template', '')
            if prompt_template:
                try:
                    prompt = prompt_template.format(original_query=original_query); response = self.summarizer_service.send(prompt)
                    if response is not None:
                        summarized = response.strip();
                        if summarized: search_query = summarized; logger.info(f'Worker: Summarized query: "{search_query}"')
                        else: logger.warning("Worker: Summarizer returned empty response.")
                    else: logger.warning("Worker: Summarizer returned None response.")
                except Exception as e: logger.error(f"Worker: Query summarization failed: {e}."); self.stream_error.emit(f"Summarization failed: {e}"); search_query = original_query if original_query is not None else ""
            else: logger.warning("Worker: Summarizer prompt template empty.")
        else: logger.debug(f"Skipping query summarization (Enabled:{summarizer_enabled}, Service:{summarizer_available}, Query:{bool(original_query)})")
        return search_query if search_query is not None else ""

    def _gather_external_rag_context(self, search_query: str, available_tokens: int) -> tuple[List[str], int]:
        """Gathers External RAG context, respecting token limits and interruption."""
        parts: List[str] = []; tokens_used: int = 0; max_results_per_source: int = self.settings.get('rag_max_results_per_source', 3); max_ranked_results_to_use: int = self.settings.get('rag_max_ranked_results', 5)
        logger.debug(f"Worker: Gathering External RAG (Budget: {available_tokens}). Query: '{search_query[:50]}...'")
        try:
            if self._is_interruption_requested(): logger.info("Worker: Stop requested before external RAG fetch."); return [], 0
            fetched_results = rag_service.fetch_external_sources_parallel(search_query=search_query, settings=self.settings, max_results_per_source=max_results_per_source)
            if self._is_interruption_requested(): logger.info("Worker: Stop requested after external RAG fetch."); return [], 0
            if not fetched_results: logger.info("Worker: No raw results from external sources."); return [], 0
            if self._is_interruption_requested(): logger.info("Worker: Stop requested before external RAG ranking."); return [], 0
            ranked_results = rag_service.filter_and_rank_results(results=fetched_results, query=search_query, max_results_to_return=max_ranked_results_to_use, settings=self.settings)
            if self._is_interruption_requested(): logger.info("Worker: Stop requested after external RAG ranking."); return [], 0
            if not ranked_results: logger.info("Worker: No external results passed ranking."); return [], 0
            logger.debug(f"Worker: Processing {len(ranked_results)} ranked external results...")
            for result in ranked_results:
                if self._is_interruption_requested(): logger.info("Worker: Stop requested during External RAG formatting."); break
                if available_tokens <= 0: logger.info("Worker: Token budget reached during Ext RAG formatting."); break
                source=result.get('source','Web').capitalize(); title=result.get('title','N/A'); url=result.get('url',''); snippet=result.get('text_snippet','').strip()
                if snippet:
                    header=f'### External RAG: {source} - {title} ({url}) ###'; footer='### End External RAG ###'
                    h_tok=count_tokens(header); s_tok=count_tokens(snippet); f_tok=count_tokens(footer); total=h_tok+s_tok+f_tok
                    if s_tok <= 0: continue
                    if total <= available_tokens: parts.append(f'{header}\n{snippet}\n{footer}'); available_tokens -= total; tokens_used += total; logger.debug(f"Worker: Added Ext RAG '{title[:30]}' ({total} tokens). Rem: {available_tokens}")
                    else:
                        needed=max(0, available_tokens - h_tok - f_tok - 10)
                        if needed > 0:
                            ratio = needed/s_tok if s_tok else 0; cutoff=int(len(snippet)*ratio); trunc=snippet[:cutoff]; tok=count_tokens(trunc); final_total=h_tok+tok+f_tok
                            if tok>0 and final_total<=available_tokens: parts.append(f'{header}\n{trunc}\n{footer}'); available_tokens -= final_total; tokens_used += final_total; logger.warning(f'Worker: Truncated Ext RAG "{title[:30]}" ({tok} snippet tokens). Rem: {available_tokens}')
                            else: logger.debug(f"Worker: Skipping Ext RAG '{title[:30]}' - Truncation failed/budget too small.")
                        else: logger.debug(f"Worker: Skipping Ext RAG '{title[:30]}' - No budget left for content.")
                else: logger.debug(f"Worker: Skipping Ext RAG result with empty snippet: {title[:30]}")
        except Exception as e: logger.exception("Worker: Error during External RAG fetching/processing"); self.stream_error.emit(f"External RAG Error: {e}")
        logger.info(f"Worker: External RAG complete. Added {len(parts)} results. Tokens used here: {tokens_used}.")
        return parts, tokens_used

    def _gather_local_rag_context(self, available_tokens: int) -> tuple[List[str], int]:
        """Gathers Local RAG context, respecting token limits and interruption."""
        parts: List[str] = []; tokens_used: int = 0; sources_processed: int = 0
        local_rag_sources = self.settings.get('rag_local_sources', [])
        logger.debug(f"Worker: Gathering Local RAG for {len(local_rag_sources)} sources (Budget: {available_tokens})...")
        if not local_rag_sources: return [], 0
        for source_info in local_rag_sources:
            if self._is_interruption_requested(): logger.info("Worker: Stop requested during Local RAG gathering."); break
            if available_tokens <= 0: logger.info("Worker: Token budget reached during Local RAG gathering."); break
            if source_info.get('enabled', False):
                path_str = source_info.get('path')
                if not path_str: logger.warning("Worker: Skipping Local RAG source with no path."); continue
                try:
                    path = Path(path_str).resolve()
                    if path.is_file():
                        try:
                            if self._is_interruption_requested(): break
                            text = path.read_text(encoding='utf-8', errors='ignore')
                            if not text: logger.debug(f"Worker: Skipping empty Local RAG file: {path.name}"); continue
                            header = f'### Local RAG File: {path_str} ###'; footer = '### End Local RAG File ###'
                            h_tok=count_tokens(header); s_tok=count_tokens(text); f_tok=count_tokens(footer); total = h_tok + s_tok + f_tok
                            if s_tok <= 0: continue
                            if total <= available_tokens: parts.append(f'{header}\n{text}\n{footer}'); available_tokens -= total; tokens_used += total; sources_processed += 1; logger.debug(f"Worker: Added Local RAG file '{path.name}' ({total} tokens). Rem: {available_tokens}")
                            else:
                                needed = max(0, available_tokens - h_tok - f_tok - 10)
                                if needed > 0:
                                    ratio = needed / s_tok if s_tok else 0; cutoff = int(len(text) * ratio); trunc = text[:cutoff]; tok = count_tokens(trunc); final_total = h_tok + tok + f_tok
                                    if tok > 0 and final_total <= available_tokens: parts.append(f'{header}\n{trunc}\n{footer}'); available_tokens -= final_total; tokens_used += final_total; sources_processed += 1; logger.warning(f'Worker: Truncated Local RAG file {path.name} ({tok} snippet tokens). Rem: {available_tokens}')
                                    else: logger.debug(f"Worker: Skipping Local RAG file {path.name} - Truncation failed/budget too small.")
                                else: logger.debug(f"Worker: Skipping Local RAG file {path.name} - No budget for content.")
                        except OSError as e: logger.warning(f"Worker: OS Error reading Local RAG file {path}: {e}")
                        except Exception as e: logger.warning(f"Worker: Error processing Local RAG file {path}: {e}")
                    elif path.is_dir(): logger.warning(f"Worker: Directory processing for Local RAG source '{path_str}' not implemented.") # TODO
                    else: logger.warning(f"Worker: Local RAG source path not valid file/dir: {path_str}")
                except Exception as e: logger.warning(f"Task: Failed to process Local RAG source '{path_str}': {e}")
        logger.info(f"Worker: Local RAG complete. Processed {sources_processed} enabled sources. Tokens used here: {tokens_used}.")
        return parts, tokens_used


    # --- Helper Method: Prepare Final Prompt ---
    def _prepare_final_prompt(self, history: list, user_query: str, context_parts: dict) -> str:
        """Formats the final prompt using the template from settings."""
        template = self.settings.get('main_prompt_template', '').strip() or DEFAULT_PROMPT_TEMPLATE
        system_prompt = self.settings.get('system_prompt', '').strip()

        # Format chat history (excluding the last user query which is separate)
        history_str_parts = []
        limit = len(history) - 1 # Process all messages except the last one (current user query)
        for msg in history[:limit]:
            role = msg.get('role', 'System').capitalize()
            content = msg.get('content', '').strip()
            if content:
                history_str_parts.append(f"{role}:\n{content}")
        history_str = "\n---\n".join(history_str_parts) if history_str_parts else "[No previous conversation]"

        # Format context parts
        code_context_str = "\n\n".join(context_parts.get('code', [])).strip() or "[No relevant code context provided]"
        local_context_str = "\n\n".join(context_parts.get('local', [])).strip() or "[No relevant local context provided]"
        remote_context_str = "\n\n".join(context_parts.get('remote', [])).strip() or "[No relevant remote context provided]"

        # *** CORRECTED DICTIONARY DEFINITION ***
        placeholder_values = {
            'system_prompt': system_prompt,
            'chat_history': history_str,
            'code_context': code_context_str,
            'local_context': local_context_str,
            'remote_context': remote_context_str,
            'user_query': user_query  # The current user query passed in
        }
        # *** END CORRECTION ***

        try:
            final_prompt = template.format(**placeholder_values)
            logger.debug(f"Worker: Prepared final prompt ({count_tokens(final_prompt)} tokens). Preview: '{final_prompt[:100]}...'")
            return final_prompt.strip()
        except KeyError as e:
            logger.error(f"Prompt template error: Missing placeholder {e}. Template:\n{template}")
            self.stream_error.emit(f"Prompt template error: Missing {e}")
            # Use the corrected placeholder_values dict for fallback
            fallback_prompt = f"<SYSTEM_PROMPT>\n{placeholder_values.get('system_prompt', '')}\n</SYSTEM_PROMPT>\n\n<CONTEXT_SOURCES>\nCode:\n{placeholder_values.get('code_context', '')}\nLocal:\n{placeholder_values.get('local_context', '')}\nRemote:\n{placeholder_values.get('remote_context', '')}\n</CONTEXT_SOURCES>\n\n<USER_QUERY>\n{placeholder_values.get('user_query', '')}\n</USER_QUERY>\n\nAssistant Response:"
            logger.warning(f"Using fallback prompt structure due to template KeyError.")
            return fallback_prompt
        except Exception as e:
             logger.exception(f"Error formatting prompt template: {e}")
             self.stream_error.emit(f"Prompt template error: {e}")
             # Use the corrected placeholder_values dict for fallback
             fallback_prompt = f"<SYSTEM_PROMPT>\n{placeholder_values.get('system_prompt', '')}\n</SYSTEM_PROMPT>\n\n<CONTEXT_SOURCES>\nCode:\n{placeholder_values.get('code_context', '')}\nLocal:\n{placeholder_values.get('local_context', '')}\nRemote:\n{placeholder_values.get('remote_context', '')}\n</CONTEXT_SOURCES>\n\n<USER_QUERY>\n{placeholder_values.get('user_query', '')}\n</USER_QUERY>\n\nAssistant Response:"
             logger.warning(f"Using fallback prompt structure due to general template error.")
             return fallback_prompt


    # --- Main Processing Method (Slot) ---
    @Slot()
    def process(self):
        """The main execution logic, called when the worker starts."""
        logger.info("Worker process started.")
        total_tokens_used = 0
        # Context parts dictionary stores lists of formatted context strings
        context_parts = {'code': [], 'local': [], 'remote': []}

        try:
            if self._is_interruption_requested(): return

            self.status_update.emit("Preparing...")
            # Calculate available token budget, reserving some for response/overhead
            max_tokens = self.settings.get('context_limit', DEFAULT_CONFIG['context_limit'])
            # Ensure max_tokens is valid positive integer
            if not isinstance(max_tokens, int) or max_tokens <= 0:
                 logger.warning(f"Invalid context_limit '{max_tokens}' in settings, using default.")
                 max_tokens = DEFAULT_CONFIG['context_limit']
            # Reserve space for I/O formatting and the LLM's response itself
            available_tokens = max(0, max_tokens - RESERVE_FOR_IO - 500) # Adjusted reservation slightly

            # --- Extract Original Query ---
            original_query = ""
            if self.history and self.history[-1].get('role') == 'user':
                 original_query = self.history[-1].get('content', '').strip()
            if not original_query:
                 # This should not happen with the fix in MainWindow._send_prompt
                 logger.error("Worker could not find user query in history snapshot.")
                 raise ValueError("Could not find user query in history.")

            # --- Query Summarization (Conditional) ---
            search_query = original_query # Default to original if not summarized
            summarizer_enabled = self.settings.get('rag_summarizer_enabled', False)
            # Check if *any* external source that benefits from summarization is enabled
            external_rag_will_run = (
                self.settings.get('rag_external_enabled', False) or # Master switch (if used)
                self.settings.get('rag_google_enabled', False) or
                self.settings.get('rag_bing_enabled', False) or
                self.settings.get('rag_stackexchange_enabled', False) or
                self.settings.get('rag_github_enabled', False) or
                self.settings.get('rag_arxiv_enabled', False)
            )

            if summarizer_enabled and external_rag_will_run and self.summarizer_service:
                logger.info("Summarizer and external RAG enabled, attempting query summarization.")
                search_query = self._summarize_query(original_query)
            elif summarizer_enabled and not external_rag_will_run:
                 logger.debug("Summarizer enabled, but no external RAG sources active. Skipping summarization.")
            else:
                 logger.debug("Query summarization skipped (disabled or no service/external sources).")


            if self._is_interruption_requested(): return

            # --- Gather Context ---

            # 1. External RAG Context (Web, APIs) - Uses summarized query if available
            # Check the master 'rag_external_enabled' flag OR individual source flags
            if external_rag_will_run and available_tokens > 0:
                self.status_update.emit("Fetching external sources...")
                # Pass the potentially summarized query
                parts, tokens = self._gather_external_rag_context(search_query, available_tokens)
                if parts: context_parts['remote'] = parts
                available_tokens = max(0, available_tokens - tokens)
                total_tokens_used += tokens
                logger.info(f"External RAG used {tokens} tokens. Available: {available_tokens}")
                if self._is_interruption_requested(): return
            else:
                logger.debug("Skipping external RAG fetch (disabled or no tokens).")


            # 2. Local RAG Context (Explicitly added sources from settings)
            # This uses the specific 'rag_local_enabled' flag from settings
            if self.settings.get('rag_local_enabled', False) and available_tokens > 0:
                 self.status_update.emit("Fetching local RAG sources...")
                 parts, tokens = self._gather_local_rag_context(available_tokens)
                 if parts: context_parts['local'] = parts
                 available_tokens = max(0, available_tokens - tokens)
                 total_tokens_used += tokens
                 logger.info(f"Local RAG sources used {tokens} tokens. Available: {available_tokens}")
                 if self._is_interruption_requested(): return
            else:
                 logger.debug("Skipping local RAG sources fetch (disabled or no tokens).")

            # 3. Tree Context (Files checked in the main UI)
            # *** FIX: Run if checked_file_paths exist, independent of 'rag_local_enabled' ***
            if self.checked_file_paths and available_tokens > 0:
                 self.status_update.emit("Gathering checked file context...")
                 parts, tokens = self._gather_tree_context(available_tokens)
                 # Assign tree context to the 'code' key for the template
                 if parts: context_parts['code'] = parts
                 available_tokens = max(0, available_tokens - tokens)
                 total_tokens_used += tokens
                 logger.info(f"Checked file context used {tokens} tokens. Available: {available_tokens}")
                 if self._is_interruption_requested(): return
            elif self.checked_file_paths:
                 logger.debug("Skipping checked file context (no tokens available).")
            else:
                 logger.debug("Skipping checked file context (no files checked).")


            logger.info(f"Worker: Context gathering complete. Total tokens used for context: {total_tokens_used}")
            self.context_info.emit(total_tokens_used, max_tokens) # Report context usage

            # --- Prepare and Stream ---
            self.status_update.emit("Preparing final prompt...")
            final_prompt = self._prepare_final_prompt(self.history, original_query, context_parts)
            final_prompt_tokens = count_tokens(final_prompt)
            logger.info(f"Final prompt prepared. Estimated tokens: {final_prompt_tokens} / {max_tokens}")
            if final_prompt_tokens > max_tokens:
                 logger.warning(f"Final prompt ({final_prompt_tokens} tokens) exceeds context limit ({max_tokens}). Truncation may occur.")
                 # Optionally emit an error or warning signal here?
                 # self.stream_error.emit("Warning: Prompt exceeds context limit!")

            if self._is_interruption_requested(): return
            if not self.model_service:
                 logger.error("Worker cannot stream: LLM service missing.")
                 raise ValueError("LLM service missing") # Raise error to stop

            self.status_update.emit("Waiting for LLM response...")
            logger.debug(f"Worker: Starting LLM stream...")

            stream_interrupted = False
            for chunk in self.model_service.stream(final_prompt):
                if self._is_interruption_requested():
                    logger.info("Worker: Stop requested during LLM stream.")
                    stream_interrupted = True
                    break
                self.stream_chunk.emit(chunk) # Emit raw chunk

            if stream_interrupted:
                logger.info("Worker: Stream finished due to interruption.")
            else:
                logger.info("Worker: Stream finished normally.")

        except Exception as e:
            logger.exception("Error occurred in worker process:") # Log full traceback
            # Avoid emitting error if interruption was the likely cause
            if not self._is_interruption_requested():
                 self.stream_error.emit(f"Worker Error: {e}")
            else:
                 logger.info(f"Worker error likely due to interruption request: {e}")
        finally:
            # Ensure finished signal is always emitted
            logger.debug("Worker: Emitting finished signal from finally block.")
            self.stream_finished.emit()