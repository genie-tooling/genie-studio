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
        self._current_thread : Optional[QThread] = None
        self._interruption_requested_flag = False # Internal flag
        logger.debug("Worker initialized.")

    # --- Add this method ---
    def assign_thread(self, thread: QThread):
        """Stores a reference to the thread this worker will run on."""
        logger.debug(f"Worker: Assigning thread {thread.objectName()}")
        self._current_thread = thread
    # --- End Added method ---

    @Slot()
    def request_interruption(self):
        """Sets the internal interruption flag."""
        logger.debug("Worker: Interruption flag set.")
        self._interruption_requested_flag = True

    def _is_interruption_requested(self) -> bool:
        """Checks the internal flag and the owning thread's request."""
        if self._interruption_requested_flag:
            return True
        # Check thread directly using the stored reference
        # Use QThread.currentThread() as a fallback if reference wasn't set (shouldn't happen now)
        thread_to_check = self._current_thread if self._current_thread else QThread.currentThread()
        return thread_to_check and thread_to_check.isInterruptionRequested()

    # --- Helper Methods for Context Gathering (Add checks) ---
    def _gather_tree_context(self, available_tokens: int) -> tuple[List[str], int]:
        parts: List[str] = []; tokens_used: int = 0; files_processed: int = 0
        project_path: Path = self.project_path
        logger.debug(f"Worker: Gathering Tree context for {len(self.checked_file_paths)} files (Budget: {available_tokens}).")
        if not self.checked_file_paths: return [], 0
        for path in self.checked_file_paths:
            if self._is_interruption_requested(): logger.info("Worker: Stop requested during Tree context."); break # <<< CHECK
            if available_tokens <= 0: logger.info("Worker: Token budget reached during Tree context."); break
            if not path.is_file(): continue
            try:
                text = path.read_text(encoding='utf-8', errors='ignore')
                if not text: continue
                try: relative_path_str = str(path.relative_to(project_path))
                except ValueError: relative_path_str = path.name
                header = f'#{relative_path_str}'
                header_tok = count_tokens(header) + 1; snippet_tok = count_tokens(text); total_tok = header_tok + snippet_tok
                if snippet_tok <= 0: continue
                if total_tok <= available_tokens:
                    parts.append(f'{header}\n{text}'); available_tokens -= total_tok; tokens_used += total_tok; files_processed += 1
                else:
                    needed_snippet_tokens = max(0, available_tokens - header_tok - 5)
                    if needed_snippet_tokens > 5:
                        ratio = needed_snippet_tokens / snippet_tok if snippet_tok > 0 else 0
                        cutoff = int(len(text) * ratio); truncated_text = text[:cutoff].strip()
                        tok = count_tokens(truncated_text); final_total_tok = header_tok + tok
                        if tok > 0 and final_total_tok <= available_tokens:
                             parts.append(f'{header}\n{truncated_text}'); available_tokens -= final_total_tok; tokens_used += final_total_tok; files_processed += 1
                             logger.warning(f'Worker: Truncated Tree file {relative_path_str} ({tok} snippet tokens). Rem: {available_tokens}')
            except OSError as e: logger.warning(f"Worker: OS Error reading Tree file {path}: {e}")
            except Exception as e: logger.warning(f"Worker: Failed to process Tree file {path}: {e}")
        logger.info(f"Worker: Tree context complete. Added {files_processed} files. Tokens used by tree: {tokens_used}.")
        return parts, tokens_used

    def _summarize_query(self, original_query: str) -> str:
        search_query = original_query if original_query is not None else ""
        summarizer_enabled = self.settings.get('rag_summarizer_enabled', False); summarizer_available = self.summarizer_service is not None; can_summarize = summarizer_enabled and summarizer_available and original_query
        if can_summarize:
            if self._is_interruption_requested(): return search_query # <<< CHECK
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
        parts: List[str] = []; tokens_used: int = 0; max_results_per_source: int = self.settings.get('rag_max_results_per_source', 3); max_ranked_results_to_use: int = self.settings.get('rag_max_ranked_results', 5)
        logger.debug(f"Worker: Gathering External RAG (Budget: {available_tokens}). Query: '{search_query[:50]}...'")
        try:
            if self._is_interruption_requested(): logger.info("Worker: Stop requested before external RAG fetch."); return [], 0 # <<< CHECK
            fetched_results = rag_service.fetch_external_sources_parallel(search_query=search_query, settings=self.settings, max_results_per_source=max_results_per_source)
            if self._is_interruption_requested(): logger.info("Worker: Stop requested after external RAG fetch."); return [], 0 # <<< CHECK
            if not fetched_results: logger.info("Worker: No raw results from external sources."); return [], 0
            if self._is_interruption_requested(): logger.info("Worker: Stop requested before external RAG ranking."); return [], 0 # <<< CHECK
            ranked_results = rag_service.filter_and_rank_results(results=fetched_results, query=search_query, max_results_to_return=max_ranked_results_to_use, settings=self.settings)
            if self._is_interruption_requested(): logger.info("Worker: Stop requested after external RAG ranking."); return [], 0 # <<< CHECK
            if not ranked_results: logger.info("Worker: No external results passed ranking."); return [], 0
            logger.debug(f"Worker: Processing {len(ranked_results)} ranked external results...")
            for result in ranked_results:
                if self._is_interruption_requested(): logger.info("Worker: Stop requested during External RAG formatting."); break # <<< CHECK
                if available_tokens <= 0: logger.info("Worker: Token budget reached during Ext RAG formatting."); break
                source=result.get('source','Web').capitalize(); title=result.get('title','N/A'); url=result.get('url',''); snippet=result.get('text_snippet','').strip()
                if snippet:
                    header=f'### External RAG: {source} - {title} ({url}) ###'; footer='### End External RAG ###'
                    h_tok=count_tokens(header); s_tok=count_tokens(snippet); f_tok=count_tokens(footer); total=h_tok+s_tok+f_tok
                    if s_tok <= 0: continue
                    if total <= available_tokens: parts.append(f'{header}\n{snippet}\n{footer}'); available_tokens -= total; tokens_used += total; logger.trace(f"Worker: Added Ext RAG '{title[:30]}' ({total} tokens). Rem: {available_tokens}")
                    else:
                        needed=max(0, available_tokens - h_tok - f_tok - 10)
                        if needed > 0:
                            ratio = needed/s_tok if s_tok else 0; cutoff=int(len(snippet)*ratio); trunc=snippet[:cutoff]; tok=count_tokens(trunc); final_total=h_tok+tok+f_tok
                            if tok>0 and final_total<=available_tokens: parts.append(f'{header}\n{trunc}\n{footer}'); available_tokens -= final_total; tokens_used += final_total; logger.warning(f'Worker: Truncated Ext RAG "{title[:30]}" ({tok} snippet tokens). Rem: {available_tokens}')
        except Exception as e: logger.exception("Worker: Error during External RAG fetching/processing"); self.stream_error.emit(f"External RAG Error: {e}")
        logger.info(f"Worker: External RAG complete. Added {len(parts)} results. Tokens used here: {tokens_used}.")
        return parts, tokens_used

    def _gather_local_rag_context(self, available_tokens: int) -> tuple[List[str], int]:
        parts: List[str] = []; tokens_used: int = 0; sources_processed: int = 0
        local_rag_sources = self.settings.get('rag_local_sources', [])
        logger.debug(f"Worker: Gathering Local RAG for {len(local_rag_sources)} sources (Budget: {available_tokens})...")
        if not local_rag_sources: return [], 0
        for source_info in local_rag_sources:
            if self._is_interruption_requested(): logger.info("Worker: Stop requested during Local RAG gathering."); break # <<< CHECK
            if available_tokens <= 0: logger.info("Worker: Token budget reached during Local RAG gathering."); break
            if source_info.get('enabled', False):
                path_str = source_info.get('path')
                if not path_str: logger.warning("Worker: Skipping Local RAG source with no path."); continue
                try:
                    path = Path(path_str).resolve()
                    if path.is_file():
                        try:
                            if self._is_interruption_requested(): break # <<< CHECK
                            text = path.read_text(encoding='utf-8', errors='ignore')
                            if not text: logger.trace(f"Worker: Skipping empty Local RAG file: {path.name}"); continue
                            header = f'### Local RAG File: {path_str} ###'; footer = '### End Local RAG File ###'
                            h_tok=count_tokens(header); s_tok=count_tokens(text); f_tok=count_tokens(footer); total = h_tok + s_tok + f_tok
                            if s_tok <= 0: continue
                            if total <= available_tokens: parts.append(f'{header}\n{text}\n{footer}'); available_tokens -= total; tokens_used += total; sources_processed += 1; logger.trace(f"Worker: Added Local RAG file '{path.name}' ({total} tokens). Rem: {available_tokens}")
                            else:
                                needed = max(0, available_tokens - h_tok - f_tok - 10)
                                if needed > 0:
                                    ratio = needed / s_tok if s_tok else 0; cutoff = int(len(text) * ratio); trunc = text[:cutoff]; tok = count_tokens(trunc); final_total = h_tok + tok + f_tok
                                    if tok > 0 and final_total <= available_tokens: parts.append(f'{header}\n{trunc}\n{footer}'); available_tokens -= final_total; tokens_used += final_total; sources_processed += 1; logger.warning(f'Worker: Truncated Local RAG file {path.name} ({tok} snippet tokens). Rem: {available_tokens}')
                        except OSError as e: logger.warning(f"Worker: OS Error reading Local RAG file {path}: {e}")
                        except Exception as e: logger.warning(f"Worker: Error processing Local RAG file {path}: {e}")
                    elif path.is_dir(): logger.warning(f"Worker: Directory processing for Local RAG source '{path_str}' not implemented.")
                    else: logger.warning(f"Worker: Local RAG source path not valid file/dir: {path_str}")
                except Exception as e: logger.warning(f"Task: Failed to process Local RAG source '{path_str}': {e}")
        logger.info(f"Worker: Local RAG complete. Processed {sources_processed} enabled sources. Tokens used here: {tokens_used}.")
        return parts, tokens_used

    # --- Helper Method: Prepare Final Prompt (Unchanged) ---
    def _prepare_final_prompt(self, history: list, user_query: str, context_parts: dict) -> str:
        template = self.settings.get('main_prompt_template', '').strip() or DEFAULT_PROMPT_TEMPLATE
        system_prompt = self.settings.get('system_prompt', '').strip()
        history_str_parts = []
        last_user_idx = -1
        for i in range(len(history) - 1, -1, -1):
            if history[i].get('role') == 'user': last_user_idx = i; break
        limit = last_user_idx if last_user_idx != -1 else len(history)
        for msg in history[:limit]:
            role = msg.get('role', 'System').capitalize(); content = msg.get('content', '').strip()
            if content: history_str_parts.append(f"{role}:\n{content}")
        history_str = "\n---\n".join(history_str_parts) if history_str_parts else "[No previous conversation]"
        code_context_str = "\n".join(context_parts.get('code', [])).strip() or "[No relevant code context provided]"
        local_context_str = "\n\n".join(context_parts.get('local', [])).strip() or "[No relevant local context provided]"
        remote_context_str = "\n\n".join(context_parts.get('remote', [])).strip() or "[No relevant remote context provided]"
        placeholder_values = {'system_prompt': system_prompt,'chat_history': history_str,'code_context': code_context_str,'local_context': local_context_str,'remote_context': remote_context_str,'user_query': user_query}
        try:
            final_prompt = template.format(**placeholder_values)
            final_prompt = final_prompt.replace('\n\n\n','\n\n').strip()
            logger.debug(f"Worker: Prepared final prompt ({count_tokens(final_prompt)} tokens). Preview: '{final_prompt[:150]}...'")
            return final_prompt
        except KeyError as e:
            logger.error(f"Prompt template error: Missing placeholder {e}. Template:\n{template}")
            self.stream_error.emit(f"Prompt template error: Missing {e}")
            fallback_prompt = f"<SYSTEM_PROMPT>\n{placeholder_values.get('system_prompt', '')}\n</SYSTEM_PROMPT>\n\n<CONTEXT_SOURCES>\nCode:\n{placeholder_values.get('code_context', '')}\nLocal:\n{placeholder_values.get('local_context', '')}\nRemote:\n{placeholder_values.get('remote_context', '')}\n</CONTEXT_SOURCES>\n\n<USER_QUERY>\n{placeholder_values.get('user_query', '')}\n</USER_QUERY>\n\nAssistant Response:"
            logger.warning(f"Using fallback prompt structure due to template KeyError.")
            return fallback_prompt
        except Exception as e:
             logger.exception(f"Error formatting prompt template: {e}")
             self.stream_error.emit(f"Prompt template error: {e}")
             fallback_prompt = f"<SYSTEM_PROMPT>\n{placeholder_values.get('system_prompt', '')}\n</SYSTEM_PROMPT>\n\n<CONTEXT_SOURCES>\nCode:\n{placeholder_values.get('code_context', '')}\nLocal:\n{placeholder_values.get('local_context', '')}\nRemote:\n{placeholder_values.get('remote_context', '')}\n</CONTEXT_SOURCES>\n\n<USER_QUERY>\n{placeholder_values.get('user_query', '')}\n</USER_QUERY>\n\nAssistant Response:"
             logger.warning(f"Using fallback prompt structure due to general template error.")
             return fallback_prompt

    # --- Main Processing Method (Slot) ---
    @Slot()
    def process(self):
        logger.info("Worker process started.")
        total_tokens_used = 0
        context_parts = {'code': [], 'local': [], 'remote': []}
        stream_interrupted = False # Flag to track if stop happened during stream

        try:
            if self._is_interruption_requested(): logger.info("Worker interrupted before processing start."); return

            self.status_update.emit("Preparing...")
            max_tokens = self.settings.get('context_limit', DEFAULT_CONFIG['context_limit'])
            if not isinstance(max_tokens, int) or max_tokens <= 0: max_tokens = DEFAULT_CONFIG['context_limit']
            available_tokens = max(0, max_tokens - RESERVE_FOR_IO - 500)
            original_query = ""
            for i in range(len(self.history) - 1, -1, -1):
                if self.history[i].get('role') == 'user': original_query = self.history[i].get('content', '').strip(); break
            if not original_query: raise ValueError("Could not find any user message in history snapshot.")

            search_query = original_query
            summarizer_enabled = self.settings.get('rag_summarizer_enabled', False)
            external_rag_will_run = ( self.settings.get('rag_external_enabled', False) or self.settings.get('rag_google_enabled', False) or self.settings.get('rag_bing_enabled', False) or self.settings.get('rag_stackexchange_enabled', False) or self.settings.get('rag_github_enabled', False) or self.settings.get('rag_arxiv_enabled', False) )
            if summarizer_enabled and external_rag_will_run and self.summarizer_service:
                search_query = self._summarize_query(original_query)
            if self._is_interruption_requested(): logger.info("Worker interrupted after query processing."); return

            # --- Gather Context ---
            if external_rag_will_run and available_tokens > 0:
                self.status_update.emit("Fetching external sources...")
                parts, tokens = self._gather_external_rag_context(search_query, available_tokens)
                if parts: context_parts['remote'] = parts
                available_tokens = max(0, available_tokens - tokens); total_tokens_used += tokens
                logger.info(f"External RAG used {tokens} tokens. Available: {available_tokens}")
                if self._is_interruption_requested(): logger.info("Worker interrupted after external RAG."); return
            else: logger.debug("Skipping external RAG fetch (disabled or no tokens).")

            if self.settings.get('rag_local_enabled', False) and available_tokens > 0:
                 self.status_update.emit("Fetching local RAG sources...")
                 parts, tokens = self._gather_local_rag_context(available_tokens)
                 if parts: context_parts['local'] = parts
                 available_tokens = max(0, available_tokens - tokens); total_tokens_used += tokens
                 logger.info(f"Local RAG sources used {tokens} tokens. Available: {available_tokens}")
                 if self._is_interruption_requested(): logger.info("Worker interrupted after local RAG."); return
            else: logger.debug("Skipping local RAG sources fetch (disabled or no tokens).")

            if self.checked_file_paths and available_tokens > 0:
                 self.status_update.emit("Gathering checked file context...")
                 parts, tokens = self._gather_tree_context(available_tokens)
                 if parts: context_parts['code'] = parts
                 available_tokens = max(0, available_tokens - tokens); total_tokens_used += tokens
                 logger.info(f"Checked file context used {tokens} tokens. Available: {available_tokens}")
                 if self._is_interruption_requested(): logger.info("Worker interrupted after tree context."); return
            elif self.checked_file_paths: logger.debug("Skipping checked file context (no tokens available).")
            else: logger.debug("Skipping checked file context (no files checked).")

            logger.info(f"Worker: Context gathering complete. Total tokens used for context: {total_tokens_used}")
            self.context_info.emit(total_tokens_used, max_tokens)

            # --- Prepare and Stream ---
            self.status_update.emit("Preparing final prompt...")
            final_prompt = self._prepare_final_prompt(self.history, original_query, context_parts)
            final_prompt_tokens = count_tokens(final_prompt)
            logger.info(f"Final prompt prepared. Estimated tokens: {final_prompt_tokens} / {max_tokens}")
            if final_prompt_tokens > max_tokens: logger.warning(f"Final prompt ({final_prompt_tokens} tokens) exceeds context limit ({max_tokens}). Truncation may occur.")
            if self._is_interruption_requested(): logger.info("Worker interrupted before LLM stream."); return
            if not self.model_service: raise ValueError("LLM service missing")

            self.status_update.emit("Waiting for LLM response...")
            logger.debug(f"Worker: Starting LLM stream...")
            for chunk in self.model_service.stream(final_prompt):
                if self._is_interruption_requested():
                    logger.info("Worker: Stop requested during LLM stream.")
                    stream_interrupted = True; break
                self.stream_chunk.emit(chunk)

            if stream_interrupted: logger.info("Worker: Stream finished due to interruption request.")
            else: logger.info("Worker: Stream finished normally.")

        except Exception as e:
            logger.exception("Error occurred in worker process:")
            if not self._is_interruption_requested(): # Don't emit error if it was likely due to stop request
                 self.stream_error.emit(f"Worker Error: {type(e).__name__}: {e}")
            else:
                 logger.info(f"Worker error occurred, but likely due to interruption request: {e}")
        finally:
            # Ensure finished signal is always emitted
            logger.debug("Worker: Emitting finished signal from finally block.")
            self.stream_finished.emit()