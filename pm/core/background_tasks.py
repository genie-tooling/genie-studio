# pm/core/background_tasks.py
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, QThread, Qt
from loguru import logger
from pathlib import Path
import time
import re
import json
import fnmatch
from typing import List, Dict, Optional, Any

from .token_utils import count_tokens
from . import rag_service
from .gemini_service import GeminiService
from .ollama_service import OllamaService
from .project_config import DEFAULT_CONFIG, get_effective_prompt, DEFAULT_RAG_INCLUDE_PATTERNS, DEFAULT_RAG_EXCLUDE_PATTERNS

RESERVE_FOR_IO = 1024
MAX_CRITIC_LOOPS = 3
# --- Increased buffer for binary check ---
BINARY_CHECK_BUFFER_SIZE = 1024
# --- Threshold for non-text characters indicating binary ---
BINARY_THRESHOLD = 0.10 # 10% non-text chars might indicate binary

class Worker(QObject):
    # (pyqtSignals remain the same)
    status_update = pyqtSignal(str)
    context_info = pyqtSignal(int, int)
    stream_chunk = pyqtSignal(str)
    stream_error = pyqtSignal(str)
    stream_finished = pyqtSignal()
    plan_generated = pyqtSignal(list)
    plan_critiqued = pyqtSignal(dict)
    plan_accepted = pyqtSignal(list)

    def __init__(self,
                 settings: dict,
                 history: list,
                 main_services: dict,
                 checked_file_paths: List[Path],
                 project_path: Path,
                 disable_critic: bool,
                 resolved_context_limit: int):
        super().__init__()
        self.settings = settings
        self.history = history
        self.model_service: Optional[OllamaService | GeminiService] = main_services.get('model_service')
        self.summarizer_service: Optional[OllamaService | GeminiService] = main_services.get('summarizer_service')
        self.checked_paths = checked_file_paths
        self.project_path = project_path
        self.disable_critic_workflow = disable_critic
        self.resolved_context_limit = resolved_context_limit
        self._current_thread : Optional[QThread] = None
        logger.debug(f"Worker initialized (Critic Disabled: {self.disable_critic_workflow}, Limit: {self.resolved_context_limit}).")

    def assign_thread(self, thread: QThread):
        logger.debug(f"Worker: Assigning thread {thread.objectName()}")
        self._current_thread = thread

    @pyqtSlot()
    def request_interruption(self):
        logger.debug("Worker: Interruption requested via pyqtSlot.")
        if self._current_thread: self._current_thread.requestInterruption()
        else: logger.warning("Worker: Cannot request interruption, owning thread missing.")

    def _is_interruption_requested(self) -> bool:
        thread_to_check = self._current_thread or QThread.currentThread()
        return thread_to_check and thread_to_check.isInterruptionRequested()

    def _gather_context(self, max_tokens_ignored: int) -> tuple[dict, int, int]:
        logger.debug("Worker: Starting context gathering.")
        max_limit = self.resolved_context_limit
        logger.info(f"Worker: Using resolved context limit: {max_limit}")
        total_context_tokens = 0
        available_tokens = max(0, max_limit - RESERVE_FOR_IO - 500)
        context_parts = {'code': [], 'local': [], 'remote': []}
        original_query = ""; chat_history_str = ""

        # Extract Query & History (same as before)
        for i in range(len(self.history) - 1, -1, -1):
            if self.history[i].get('role') == 'user': original_query = self.history[i].get('content', '').strip(); break
        if not original_query: raise ValueError("User query not found.")
        history_str_parts = []; last_user_idx = -1
        for i in range(len(self.history) - 1, -1, -1):
            if self.history[i].get('role') == 'user': last_user_idx = i; break
        limit = last_user_idx if last_user_idx != -1 else len(self.history)
        for msg in self.history[:limit]:
            role = msg.get('role', 'System').capitalize(); content = msg.get('content', '').strip()
            if content: history_str_parts.append(f"{role}:\n{content}")
        chat_history_str = "\n---\n".join(history_str_parts) if history_str_parts else "[No previous conversation]"

        if self._is_interruption_requested(): return {}, 0, max_limit

        # Summarize for RAG
        search_query = original_query; summarizer_enabled = self.settings.get('rag_summarizer_enabled', False)
        external_rag_will_run = any(self.settings.get(key, False) for key in ['rag_external_enabled','rag_google_enabled','rag_bing_enabled','rag_stackexchange_enabled','rag_github_enabled','rag_arxiv_enabled'])
        if summarizer_enabled and external_rag_will_run and self.summarizer_service:
             self.status_update.emit("Summarizing query for RAG...")
             search_query = self._summarize_query(original_query) # Pass original query
             if self._is_interruption_requested(): return {}, total_context_tokens, max_limit

        # Gather RAG Contexts (same as before, check interruption)
        if external_rag_will_run and available_tokens > 0:
            self.status_update.emit("Fetching external RAG sources...")
            parts, tokens = self._gather_external_rag_context(search_query, available_tokens)
            if self._is_interruption_requested(): return {}, total_context_tokens, max_limit
            if parts: context_parts['remote'] = parts
            available_tokens = max(0, available_tokens - tokens); total_context_tokens += tokens
            logger.info(f"External RAG used {tokens} tokens. Available: {available_tokens}")
        else: logger.debug("Skipping external RAG.")

        if self.settings.get('rag_local_enabled', False) and available_tokens > 0:
            self.status_update.emit("Fetching local RAG sources...")
            parts, tokens = self._gather_local_rag_context(available_tokens)
            if self._is_interruption_requested(): return {}, total_context_tokens, max_limit
            if parts: context_parts['local'] = parts
            available_tokens = max(0, available_tokens - tokens); total_context_tokens += tokens
            logger.info(f"Local RAG sources used {tokens} tokens. Available: {available_tokens}")
        else: logger.debug("Skipping local RAG.")

        # Gather Checked Path Context (same as before, check interruption)
        if self.checked_paths and available_tokens > 0:
             self.status_update.emit("Gathering checked file/directory context...")
             parts, tokens = self._gather_checked_path_context(available_tokens)
             if self._is_interruption_requested(): return {}, total_context_tokens, max_limit
             if parts: context_parts['code'] = parts
             available_tokens = max(0, available_tokens - tokens); total_context_tokens += tokens
             logger.info(f"Checked path context used {tokens} tokens. Available: {available_tokens}")
        else: logger.debug("Skipping checked path context.")

        logger.info(f"Worker: Context gathering complete. Total tokens used: {total_context_tokens}")

        # Prepare Final Context (same as before)
        system_prompt_base = self.settings.get('system_prompt', DEFAULT_CONFIG['system_prompt'])
        selected_prompt_ids = self.settings.get('selected_prompt_ids', [])
        all_prompts = self.settings.get('user_prompts', []); prompts_by_id = {p['id']: p for p in all_prompts}
        user_prompt_content_parts = []
        for pid in selected_prompt_ids:
             prompt_data = prompts_by_id.get(pid)
             if prompt_data: user_prompt_content_parts.append(prompt_data['content'])
        final_system_prompt = system_prompt_base
        if user_prompt_content_parts: final_system_prompt += "\n\n--- User Instructions ---\n" + "\n\n".join(user_prompt_content_parts)
        final_context = {
            'query': original_query,
            'code_context': "\n".join(context_parts.get('code', [])).strip() or "[No code context]",
            'chat_history': chat_history_str,
            'rag_context': "\n\n".join(context_parts.get('remote', [])).strip() or "[No external context]",
            'local_context': "\n\n".join(context_parts.get('local', [])).strip() or "[No local context]",
            'system_prompt': final_system_prompt,
            'user_prompts': "[User prompts integrated into system prompt]",
        }
        self.context_info.emit(total_context_tokens, max_limit)
        return final_context, total_context_tokens, max_limit

    # --- Context Gathering Helpers ---
    def _gather_checked_path_context(self, available_tokens: int) -> tuple[List[str], int]:
        # (Directory walking logic remains the same, uses _add_file_context which now checks for binary)
        parts: List[str] = []; tokens_used: int = 0; files_processed: int = 0; dirs_processed: int = 0
        project_path: Path = self.project_path
        max_depth = self.settings.get('rag_dir_max_depth', DEFAULT_CONFIG['rag_dir_max_depth'])
        include_patterns = self.settings.get('rag_dir_include_patterns', DEFAULT_RAG_INCLUDE_PATTERNS)
        exclude_patterns = self.settings.get('rag_dir_exclude_patterns', DEFAULT_RAG_EXCLUDE_PATTERNS)
        exclude_patterns.extend(['*.patchmind.json', '.git/*'])
        logger.debug(f"Worker: Gathering Checked Path context for {len(self.checked_paths)} items (Budget: {available_tokens}, Depth: {max_depth}).")
        if not self.checked_paths: return [], 0
        def should_include_file(filepath: Path) -> bool:
            if not any(fnmatch.fnmatch(filepath.name, pattern) for pattern in include_patterns): return False
            if any(fnmatch.fnmatch(filepath.name, pattern) for pattern in exclude_patterns): return False
            try:
                relative_path_str = str(filepath.relative_to(project_path))
                if any(fnmatch.fnmatch(relative_path_str, pattern) for pattern in exclude_patterns): return False
            except ValueError: pass
            return True
        paths_to_process = list(self.checked_paths); processed_files_in_dirs = set()
        while paths_to_process:
            if self._is_interruption_requested(): break
            if available_tokens <= 0: break
            path = paths_to_process.pop(0)
            try:
                if path.is_file() and path not in processed_files_in_dirs:
                    if should_include_file(path):
                        # --- Pass to helper which now includes binary check ---
                        available_tokens, tokens_added = self._add_file_context(path, available_tokens, parts)
                        # -----------------------------------------------------
                        if tokens_added > 0: tokens_used += tokens_added; files_processed += 1; processed_files_in_dirs.add(path)
                    else: logger.trace(f"Skipping file (exclude pattern): {path.name}")
                elif path.is_dir():
                    dirs_processed += 1
                    try: current_depth = len(path.relative_to(project_path).parts)
                    except ValueError: current_depth = 0
                    if current_depth > max_depth: logger.trace(f"Skipping dir (max depth): {path.name}"); continue
                    logger.trace(f"Processing dir (Depth {current_depth}): {path.name}")
                    try:
                        for entry in path.iterdir():
                             if self._is_interruption_requested(): break
                             if any(fnmatch.fnmatch(entry.name, pattern) for pattern in exclude_patterns): logger.trace(f"Skipping entry (exclude): {entry.name}"); continue
                             if entry.is_file() and entry not in processed_files_in_dirs: paths_to_process.append(entry)
                             elif entry.is_dir(): paths_to_process.append(entry)
                    except OSError as walk_err: logger.warning(f"Error iterating dir '{path}': {walk_err}")
            except OSError as e: logger.warning(f"OS Error processing path {path}: {e}")
            except Exception as e: logger.warning(f"Failed process path {path}: {e}")
        logger.info(f"Checked Path context: Added {files_processed} files from {dirs_processed} dirs. Tokens: {tokens_used}.")
        return parts, tokens_used

    # --- MODIFIED: Add binary check ---
    def _is_likely_binary(self, file_path: Path) -> bool:
        """Heuristic check for binary files."""
        try:
            with open(file_path, 'rb') as f:
                chunk = f.read(BINARY_CHECK_BUFFER_SIZE)
            if not chunk: return False # Empty file is not binary

            # Count non-text characters (outside typical ASCII range + common control chars)
            # This is a basic heuristic and might misclassify some text files or vice-versa
            text_chars = bytes(range(32, 127)) + b'\n\r\t\f\b'
            non_text_count = sum(1 for byte in chunk if byte not in text_chars)

            ratio = non_text_count / len(chunk)
            # logger.trace(f"Binary check for {file_path.name}: Ratio={ratio:.3f}")
            return ratio > BINARY_THRESHOLD
        except Exception as e:
            logger.warning(f"Error during binary check for {file_path.name}: {e}")
            return False # Err on the side of caution? Or assume not binary? Assume not binary for now.

    def _add_file_context(self, file_path: Path, available_tokens: int, parts_list: List[str]) -> tuple[int, int]:
        """Reads a file, adds its content to parts_list if tokens allow, returns remaining tokens and tokens added."""
        # --- ADDED: Binary Check ---
        if self._is_likely_binary(file_path):
            logger.debug(f"Skipping likely binary file: {file_path.name}")
            return available_tokens, 0
        # --- END Binary Check ---

        tokens_added = 0
        try: relative_path_str = str(file_path.relative_to(self.project_path))
        except ValueError: relative_path_str = file_path.name

        try:
            fsize = file_path.stat().st_size
            if fsize > 5 * 1024 * 1024: logger.warning(f"Skipping large file: {file_path.name}"); return available_tokens, 0
            text = file_path.read_text(encoding='utf-8', errors='ignore')
            if not text: return available_tokens, 0
            header = f'### START FILE: {relative_path_str} ###'; footer = f'### END FILE: {relative_path_str} ###'
            header_tok = count_tokens(header) + 1; snippet_tok = count_tokens(text); footer_tok = count_tokens(footer) +1 ; total_tok = header_tok + snippet_tok + footer_tok
            if snippet_tok <= 0: return available_tokens, 0
            if total_tok <= available_tokens:
                parts_list.append(f'{header}\n{text}\n{footer}'); available_tokens -= total_tok; tokens_added = total_tok
                logger.trace(f"Added file '{relative_path_str}' ({tokens_added} tokens). Rem: {available_tokens}")
            else:
                needed_snippet_tokens = max(0, available_tokens - header_tok - footer_tok - 5)
                if needed_snippet_tokens > 5:
                    ratio = needed_snippet_tokens / snippet_tok if snippet_tok > 0 else 0; cutoff = int(len(text) * ratio); truncated_text = text[:cutoff].strip()
                    tok = count_tokens(truncated_text); final_total_tok = header_tok + tok + footer_tok
                    if tok > 0 and final_total_tok <= available_tokens:
                         parts_list.append(f'{header}\n{truncated_text}\n{footer}'); available_tokens -= final_total_tok; tokens_added = final_total_tok
                         logger.warning(f'Truncated file {relative_path_str} ({tok} snippet tokens). Rem: {available_tokens}')
        except OSError as e: logger.warning(f"OS Error reading file {file_path}: {e}")
        except Exception as e: logger.warning(f"Failed process file {file_path}: {e}")
        return available_tokens, tokens_added

    # --- MODIFIED: Fix placeholder name ---
    def _summarize_query(self, original_query: str) -> str:
        search_query = original_query if original_query is not None else ""
        if not self.summarizer_service: return search_query
        if self._is_interruption_requested(): return search_query
        logger.debug(f"Attempting query summarization...")
        # --- FIX: Use 'original_query' key ---
        placeholders = {'original_query': original_query, 'chat_history': "[History not used]"}
        # -----------------------------------
        try:
            prompt = get_effective_prompt(self.settings, 'rag_summarizer_prompt_template', placeholders)
            if not prompt: logger.error("Failed format RAG summarizer prompt."); return search_query # Error handled by get_effective_prompt now
            response = self.summarizer_service.send(prompt)
            if response: summarized = response.strip()
            if summarized: search_query = summarized; logger.info(f'Summarized query: "{search_query}"')
            else: logger.warning("Summarizer returned empty.")
        except Exception as e: logger.error(f"Query summarization failed: {e}."); self.stream_error.emit(f"Summarization failed: {e}"); search_query = original_query
        return search_query if search_query is not None else ""
    # ------------------------------------

    # --- Other helpers (_gather_external_rag_context, _gather_local_rag_context, _call_llm) remain the same ---
    # (Ensure they check _is_interruption_requested())
    def _gather_external_rag_context(self, search_query: str, available_tokens: int) -> tuple[List[str], int]:
        parts: List[str] = []; tokens_used: int = 0; max_res: int = self.settings.get('rag_max_results_per_source', 3); max_rank: int = self.settings.get('rag_max_ranked_results', 5)
        logger.debug(f"Gathering External RAG (Budget: {available_tokens}). Query: '{search_query[:50]}...'")
        try:
            if self._is_interruption_requested(): return [], 0
            fetched = rag_service.fetch_external_sources_parallel(search_query=search_query, settings=self.settings, max_results_per_source=max_res)
            if self._is_interruption_requested(): return [], 0
            if not fetched: return [], 0
            if self._is_interruption_requested(): return [], 0
            ranked = rag_service.filter_and_rank_results(results=fetched, query=search_query, max_results_to_return=max_rank, settings=self.settings)
            if self._is_interruption_requested(): return [], 0
            if not ranked: return [], 0
            for result in ranked:
                if self._is_interruption_requested(): break
                if available_tokens <= 0: break
                source=result.get('source','Web').capitalize(); title=result.get('title','N/A'); url=result.get('url',''); snippet=result.get('text_snippet','').strip()
                if snippet:
                    header=f'### RAG: {source} - {title} ({url}) ###'; footer='### End RAG ###'
                    h, s, f = count_tokens(header), count_tokens(snippet), count_tokens(footer); total=h+s+f+2
                    if s <= 0: continue
                    if total <= available_tokens: parts.append(f'{header}\n{snippet}\n{footer}'); available_tokens -= total; tokens_used += total
                    else:
                        needed=max(0, available_tokens - h - f - 10)
                        if needed > 5:
                            ratio=needed/s if s else 0; cutoff=int(len(snippet)*ratio); trunc=snippet[:cutoff]; tok=count_tokens(trunc); final_total=h+tok+f+2
                            if tok>0 and final_total<=available_tokens: parts.append(f'{header}\n{trunc}\n{footer}'); available_tokens -= final_total; tokens_used += final_total; logger.warning(f'Truncated Ext RAG "{title[:30]}" ({tok} tokens).')
        except Exception as e: logger.exception("Error during External RAG"); self.stream_error.emit(f"External RAG Error: {e}")
        logger.info(f"External RAG complete. Added {len(parts)} results. Tokens: {tokens_used}.")
        return parts, tokens_used

    def _gather_local_rag_context(self, available_tokens: int) -> tuple[List[str], int]:
        parts: List[str] = []; tokens_used: int = 0; processed: int = 0
        sources = self.settings.get('rag_local_sources', [])
        logger.debug(f"Gathering Local RAG for {len(sources)} sources (Budget: {available_tokens})...")
        if not sources: return [], 0
        for src_info in sources:
            if self._is_interruption_requested(): break
            if available_tokens <= 0: break
            if src_info.get('enabled', False):
                path_str = src_info.get('path');
                if not path_str: continue
                try:
                    path = Path(path_str).resolve()
                    if path.is_file():
                         # --- ADDED: Binary Check ---
                         if self._is_likely_binary(path):
                              logger.debug(f"Skipping likely binary local RAG file: {path.name}")
                              continue
                         # --------------------------
                         try:
                            if self._is_interruption_requested(): break
                            text = path.read_text(encoding='utf-8', errors='ignore')
                            if not text: continue
                            header = f'### Local File: {path_str} ###'; footer = '### End Local File ###'
                            h, s, f = count_tokens(header), count_tokens(text), count_tokens(footer); total = h + s + f + 2
                            if s <= 0: continue
                            if total <= available_tokens: parts.append(f'{header}\n{text}\n{footer}'); available_tokens -= total; tokens_used += total; processed += 1
                            else:
                                needed = max(0, available_tokens - h - f - 10)
                                if needed > 5:
                                    ratio=needed/s if s else 0; cutoff=int(len(text)*ratio); trunc=text[:cutoff]; tok=count_tokens(trunc); final_total=h+tok+f+2
                                    if tok>0 and final_total<=available_tokens: parts.append(f'{header}\n{trunc}\n{footer}'); available_tokens -= final_total; tokens_used += final_total; processed += 1; logger.warning(f'Truncated Local RAG file {path.name} ({tok} tokens).')
                         except OSError as e: logger.warning(f"OS Error reading Local RAG file {path}: {e}")
                         except Exception as e: logger.warning(f"Error processing Local RAG file {path}: {e}")
                    elif path.is_dir(): logger.warning(f"Dir processing for Local RAG source '{path_str}' not implemented.")
                except Exception as e: logger.warning(f"Failed process Local RAG source '{path_str}': {e}")
        logger.info(f"Local RAG complete. Processed {processed} sources. Tokens: {tokens_used}.")
        return parts, tokens_used

    def _call_llm(self, prompt: str, use_stream: bool = False):
        if not self.model_service: raise ValueError("LLM model service not available.")
        if use_stream: return self.model_service.stream(prompt)
        else: return self.model_service.send(prompt)

    # --- process method remains the same, uses resolved limit from _gather_context ---
    @pyqtSlot()
    def process(self):
        logger.info("Worker process started.")
        stream_interrupted = False; final_plan = []
        try:
            if self._is_interruption_requested(): return
            self.status_update.emit("Gathering context...")
            context_data, context_tokens, max_tokens = self._gather_context(self.resolved_context_limit)
            if self._is_interruption_requested(): return
            if self.disable_critic_workflow:
                logger.info("Running DIRECT EXECUTION workflow.")
                self.status_update.emit("Preparing direct execution prompt...")
                prompt = get_effective_prompt(self.settings, 'direct_executor_prompt_template', context_data)
                if not prompt: raise ValueError("Failed format direct executor prompt.")
                prompt_tokens = count_tokens(prompt)
                logger.info(f"Direct Exec prompt tokens: {prompt_tokens} / {max_tokens}")
                if prompt_tokens > max_tokens: logger.warning(f"Direct Exec prompt ({prompt_tokens} tokens) exceeds limit ({max_tokens}).")
                if self._is_interruption_requested(): return
                self.status_update.emit("Executing directly...")
                stream = self._call_llm(prompt, use_stream=True)
                for chunk in stream:
                    if self._is_interruption_requested(): stream_interrupted = True; break
                    self.stream_chunk.emit(chunk)
            else:
                logger.info("Running PLAN-CRITIC-EXECUTOR workflow.")
                if self._is_interruption_requested(): return
                self.status_update.emit("Generating execution plan...")
                prompt = get_effective_prompt(self.settings, 'planner_prompt_template', context_data)
                if not prompt: raise ValueError("Failed format planner prompt.")
                resp = self._call_llm(prompt, use_stream=False)
                if self._is_interruption_requested(): return
                proposed_plan = [ln.strip() for ln in resp.strip().split('\n') if ln.strip()]
                logger.info(f"Proposed plan:\n{proposed_plan}"); self.plan_generated.emit(proposed_plan)
                current_plan = proposed_plan; final_plan = proposed_plan; loop = 0
                while loop < MAX_CRITIC_LOOPS:
                    if self._is_interruption_requested(): return
                    self.status_update.emit(f"Critiquing plan (Attempt {loop + 1}/{MAX_CRITIC_LOOPS})...")
                    critic_ctx = context_data.copy(); critic_ctx['proposed_plan'] = "\n".join(f"{i+1}. {s}" for i, s in enumerate(current_plan))
                    prompt = get_effective_prompt(self.settings, 'critic_prompt_template', critic_ctx)
                    if not prompt: raise ValueError("Failed format critic prompt.")
                    resp_str = self._call_llm(prompt, use_stream=False)
                    if self._is_interruption_requested(): return
                    try:
                        match = re.search(r'```json\s*(\{.*?\})\s*```', resp_str, re.S|re.I) or re.search(r'^(\{.*?\})$', resp_str.strip(), re.S)
                        if match: data = json.loads(match.group(1)); self.plan_critiqued.emit(data)
                        else: logger.error(f"Critic JSON block not found. Resp:\n{resp_str}"); final_plan = current_plan; break
                        status=data.get('plan_status'); reason=data.get('critique_reasoning','N/A'); revised=data.get('revised_plan')
                        if status == 'GOOD': logger.info(f"Plan accepted. Reason: {reason}"); final_plan=current_plan; self.plan_accepted.emit(final_plan); break
                        elif status == 'BAD':
                            logger.warning(f"Plan rejected. Reason: {reason}")
                            if revised and isinstance(revised, list) and revised: logger.info(f"Using revised plan:\n{revised}"); current_plan = revised; loop += 1
                            else: logger.error("Critic rejected but no revision."); final_plan = current_plan; break
                        else: logger.error(f"Unexpected critic status '{status}'."); final_plan = current_plan; break
                    except json.JSONDecodeError as e: logger.error(f"Failed parse critic JSON: {e}. Resp:\n{resp_str}"); final_plan=current_plan; break
                    except Exception as e: logger.exception(f"Error processing critic response: {e}"); final_plan=current_plan; break
                if loop == MAX_CRITIC_LOOPS: logger.warning(f"Critic loop max attempts. Using last plan."); final_plan = current_plan; self.plan_accepted.emit(final_plan)
                if self._is_interruption_requested(): return
                self.status_update.emit("Executing final plan...")
                exec_ctx = context_data.copy(); exec_ctx['final_plan'] = "\n".join(f"{i+1}. {s}" for i, s in enumerate(final_plan))
                prompt = get_effective_prompt(self.settings, 'executor_prompt_template', exec_ctx)
                if not prompt: raise ValueError("Failed format executor prompt.")
                prompt_tokens = count_tokens(prompt)
                logger.info(f"Executor prompt tokens: {prompt_tokens} / {max_tokens}")
                if prompt_tokens > max_tokens: logger.warning(f"Executor prompt ({prompt_tokens} tokens) exceeds limit ({max_tokens}).")
                logger.debug("Starting Executor stream...")
                stream = self._call_llm(prompt, use_stream=True)
                for chunk in stream:
                    if self._is_interruption_requested(): stream_interrupted = True; break
                    self.stream_chunk.emit(chunk)
            if stream_interrupted: logger.info("Stream finished due to interruption.")
            else: logger.info("Stream finished normally.")
        except Exception as e:
            logger.exception("Error occurred in worker process:")
            if not self._is_interruption_requested(): self.stream_error.emit(f"Worker Error: {type(e).__name__}: {e}")
            else: logger.info(f"Worker error likely due to interruption: {e}")
        finally:
            logger.debug("Worker: Emitting finished pyqtSignal.")
            self.stream_finished.emit()

