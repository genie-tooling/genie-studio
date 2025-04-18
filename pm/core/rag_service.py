# pm/core/rag_service.py
"""
Service for fetching context from external RAG sources.
Uses parallel execution for DDG/Bing searches and consistent naming.
Requires: pip install -U duckduckgo-search arxiv sentence-transformers torch requests
"""
from loguru import logger
from typing import List, Dict, Any, Optional, Tuple, Callable
from duckduckgo_search import DDGS
import arxiv
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# In pm/core/rag_service.py

_loaded_model_instance: Optional['SentenceTransformer'] = None
_loaded_model_name: Optional[str] = None
_util_module: Optional[Any] = None
_has_sentence_transformers = False # Start assuming false

try:
    from sentence_transformers import SentenceTransformer, util # Attempt import
    _util_module = util
    _has_sentence_transformers = True # Set flag if import successful
    logger.info("sentence-transformers library found.")
except ImportError:
    logger.warning("sentence-transformers missing. Ranking skipped. pip install sentence-transformers torch")
except Exception as e:
    logger.error(f"Error importing sentence-transformers: {e}")

def _get_sentence_transformer_model(model_name: str) -> Optional['SentenceTransformer']:
    """Dynamically loads or retrieves the cached Sentence Transformer model."""
    global _loaded_model_instance, _loaded_model_name

    if not _has_sentence_transformers: # Check flag
        return None

    if _loaded_model_instance and _loaded_model_name == model_name:
        logger.debug(f"Using cached ST model: {model_name}")
        return _loaded_model_instance
    else:
        logger.info(f"Loading ST model: {model_name}...")
        try:
            start_time = time.time()
            # *** Directly use SentenceTransformer (it's globally available if import succeeded) ***
            new_model = SentenceTransformer(model_name)
            # **************************************************************************************
            logger.info(f"Successfully loaded model '{model_name}' in {time.time() - start_time:.2f} seconds.")
            _loaded_model_instance = new_model
            _loaded_model_name = model_name
            return _loaded_model_instance
        except Exception as e:
            logger.error(f"Failed load ST model '{model_name}': {e}")
            _loaded_model_instance = None; _loaded_model_name = None; return None

RAGResult = Dict[str, Any]
DDG_SLEEP_DURATION = 1.0 # Slightly reduced sleep

# --- Engine Specific Search Functions ---

# In pm/core/rag_service.py

def search_ddg(query: str, num_results: int = 5, region: str = 'wt-wt') -> List[RAGResult]:
    """Searches DuckDuckGo directly using positional argument for query."""
    logger.info(f"DDG Search: '{query}' (Max results: {num_results})")
    results: List[RAGResult] = []
    start_time = time.time()
    try:
        with DDGS(timeout=20) as ddgs:
             # *** PASS QUERY POSITIONALLY ***
             search_results = ddgs.text(query, region=region, max_results=num_results)
             # *******************************
             if search_results:
                  for result_item in search_results:
                       snippet = result_item.get('body', '').strip()
                       if snippet:
                           results.append({ # ... details ...
                           })
             logger.debug(f"DDG raw returned {len(results)} results in {time.time()-start_time:.2f}s.")
    except Exception as e:
        logger.error(f"DDG search failed for '{query}': {e}")
    finally:
        logger.debug(f"Sleeping {DDG_SLEEP_DURATION}s after DDG search...")
        time.sleep(DDG_SLEEP_DURATION)
    return results

def search_bing(query: str, api_key: str, num_results: int = 5) -> List[RAGResult]:
    """Searches Bing Web Search API using consistent variable names."""
    logger.info(f"Bing Search: '{query}' (Max results: {num_results})")
    results: List[RAGResult] = []
    if not api_key: logger.warning("Bing search skipped: API Key missing."); return results
    endpoint = "https://api.bing.microsoft.com/v7.0/search"
    headers = {"Ocp-Apim-Subscription-Key": api_key}
    params = {"q": query, "count": num_results, "responseFilter": "Webpages"}
    start_time = time.time()
    try:
        response = requests.get(endpoint, headers=headers, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        web_pages = data.get("webPages", {}).get("value", [])
        for page in web_pages:
            snippet = page.get("snippet", "").strip()
            if snippet:
                results.append({
                    'url': page.get("url", ""), 'title': page.get("name", "N/A"),
                    'text_snippet': snippet, 'source': 'bing'
                })
        logger.debug(f"Bing raw returned {len(results)} results in {time.time()-start_time:.2f}s.")
    except requests.exceptions.Timeout: logger.error(f"Bing search timeout for '{query}'.")
    except requests.exceptions.RequestException as e: logger.error(f"Bing search failed for '{query}': {e}")
    except Exception as e: logger.error(f"Bing search processing error: {e}")
    return results

# --- Source Specific Wrappers (Using Both Engines) ---

def search_stackexchange(query: str, bing_key: Optional[str], num_results: int = 3) -> List[RAGResult]:
    """Fetches from StackExchange using DDG and Bing."""
    logger.info(f"Fetching StackExchange for: '{query}'")
    all_source_results = []
    all_source_results.extend(search_stackexchange_ddg(query=query, num_results=num_results)) # Use keywords
    if bing_key:
         all_source_results.extend(search_stackexchange_bing(query=query, api_key=bing_key, num_results=num_results)) # Use keywords
    return all_source_results

def search_github(query: str, bing_key: Optional[str], num_results: int = 3) -> List[RAGResult]:
    """Fetches from GitHub using DDG and Bing."""
    logger.info(f"Fetching GitHub for: '{query}'")
    all_source_results = []
    all_source_results.extend(search_github_ddg(query=query, num_results=num_results)) # Use keywords
    if bing_key:
        all_source_results.extend(search_github_bing(query=query, api_key=bing_key, num_results=num_results)) # Use keywords
    return all_source_results

# --- Site Specific Wrappers for DDG (Corrected) ---
def search_stackexchange_ddg(query: str, num_results: int = 3) -> List[RAGResult]:
    """Searches Stack Overflow/Exchange via DDG site search."""
    logger.info(f"StackEx DDG Search: '{query}' (Max results: {num_results})")
    site_query = f"site:stackoverflow.com OR site:stackexchange.com {query}"
    ddg_results = search_ddg(query=site_query, num_results=num_results) # Use keywords
    for result_item in ddg_results: result_item['source'] = 'stackexchange'
    logger.info(f"Found {len(ddg_results)} potential StackEx results via DDG.")
    return ddg_results

def search_github_ddg(query: str, num_results: int = 3) -> List[RAGResult]:
    """Searches GitHub via DDG site search."""
    logger.info(f"GitHub DDG Search: '{query}' (Max results: {num_results})")
    site_query = f"site:github.com {query}"
    ddg_results = search_ddg(query=site_query, num_results=num_results) # Use keywords
    for result_item in ddg_results: result_item['source'] = 'github'
    logger.info(f"Found {len(ddg_results)} potential GitHub results via DDG.")
    return ddg_results

# --- Site Specific Wrappers for Bing (Corrected) ---
def search_stackexchange_bing(query: str, api_key: str, num_results: int = 3) -> List[RAGResult]:
    """Searches Stack Overflow/Exchange via Bing site search."""
    logger.info(f"StackEx Bing Search: '{query}' (Max results: {num_results})")
    if not api_key: logger.warning("StackEx Bing skipped: API Key missing."); return []
    site_query = f"site:stackoverflow.com OR site:stackexchange.com {query}"
    bing_results = search_bing(query=site_query, api_key=api_key, num_results=num_results) # Use keywords
    for result_item in bing_results: result_item['source'] = 'stackexchange'
    logger.debug(f"Found {len(bing_results)} potential StackEx results via Bing.")
    return bing_results

def search_github_bing(query: str, api_key: str, num_results: int = 3) -> List[RAGResult]:
    """Searches GitHub via Bing site search."""
    logger.info(f"GitHub Bing Search: '{query}' (Max results: {num_results})")
    if not api_key: logger.warning("GitHub Bing skipped: API Key missing."); return []
    site_query = f"site:github.com {query}"
    bing_results = search_bing(query=site_query, api_key=api_key, num_results=num_results) # Use keywords
    for result_item in bing_results: result_item['source'] = 'github'
    logger.debug(f"Found {len(bing_results)} potential GitHub results via Bing.")
    return bing_results

# --- ArXiv Search (Corrected) ---
def search_arxiv(query: str, num_results: int = 3) -> List[RAGResult]:
    """Searches ArXiv API using the 'arxiv' library."""
    logger.info(f"ArXiv Search: '{query}' (Max results: {num_results})")
    results: List[RAGResult] = []
    try:
        search = arxiv.Search(query=query, max_results=num_results, sort_by=arxiv.SortCriterion.Relevance)
        client = arxiv.Client()
        found_results = list(client.results(search))
        if found_results:
            for result_item in found_results: # Use different loop var name
                summary = getattr(result_item, 'summary', '').strip()
                if summary:
                    title = getattr(result_item, 'title', 'N/A'); entry_id = getattr(result_item, 'entry_id', ''); pdf_url = getattr(result_item, 'pdf_url', ''); url = entry_id if entry_id else pdf_url
                    results.append({'url': url, 'title': title, 'text_snippet': summary, 'source': 'arxiv'})
            logger.debug(f"ArXiv search returned {len(results)} results.")
        else: logger.debug(f"ArXiv search for '{query}' returned no results.")
    except ImportError: logger.error("The 'arxiv' library is not installed. pip install arxiv")
    except Exception as e: logger.error(f"ArXiv search failed for query '{query}': {e}")
    return results

# --- Parallel Fetching Function (Corrected) ---
def fetch_external_sources_parallel(
    search_query: str, settings: dict, max_results_per_source: int = 3
) -> List[RAGResult]:
    """Fetches results from enabled external sources concurrently."""
    all_results: List[RAGResult] = []
    tasks_to_run: List[Tuple[str, Callable, tuple]] = []
    bing_key = settings.get('rag_bing_api_key')
    use_bing = settings.get('rag_bing_enabled') and bing_key

    logger.info(f"Starting parallel fetch. Query: '{search_query[:50]}...'. Bing enabled: {bool(use_bing)}")

    # Define tasks using FULL argument names
    if settings.get('rag_stackexchange_enabled'):
        tasks_to_run.append(('SE_DDG', search_stackexchange_ddg, (search_query, max_results_per_source)))
        if use_bing: tasks_to_run.append(('SE_Bing', search_stackexchange_bing, (search_query, bing_key, max_results_per_source)))
    if settings.get('rag_github_enabled'):
        tasks_to_run.append(('GH_DDG', search_github_ddg, (search_query, max_results_per_source)))
        if use_bing: tasks_to_run.append(('GH_Bing', search_github_bing, (search_query, bing_key, max_results_per_source)))
    if settings.get('rag_arxiv_enabled'):
        tasks_to_run.append(('ArXiv', search_arxiv, (search_query, max_results_per_source)))
    # Add other generic searches if desired

    if not tasks_to_run: logger.info("No external RAG sources enabled."); return []

    logger.debug(f"Submitting {len(tasks_to_run)} tasks to ThreadPoolExecutor.")
    with ThreadPoolExecutor(max_workers=min(len(tasks_to_run), 8)) as executor:
        future_to_name = {executor.submit(func, *args): name for name, func, args in tasks_to_run}
        for future in as_completed(future_to_name):
            source_name = future_to_name[future]
            try:
                task_results = future.result()
                if task_results: logger.info(f"Received {len(task_results)} results from {source_name}."); all_results.extend(task_results)
                else: logger.debug(f"Source '{source_name}' returned no results.")
            except Exception as exc: logger.error(f"Source '{source_name}' generated an exception: {exc}") # Log exception from future

    logger.info(f"Total raw results fetched from all sources: {len(all_results)}")
    # Deduplication
    deduplicated_results = []; seen_urls = set()
    for result_item in all_results: 
        url = result_item.get('url'); 
        if url and url not in seen_urls: 
            deduplicated_results.append(result_item); seen_urls.add(url)
    logger.info(f"Results after deduplication by URL: {len(deduplicated_results)}")
    return deduplicated_results

# --- Ranking/Filtering (Corrected Signature) ---
def filter_and_rank_results(
    results: List[RAGResult], # Full name
    query: str,               # Full name
    max_results_to_return: int, # Full name
    settings: dict            # Full name
    ) -> List[RAGResult]:
    """Filters and ranks RAG results using consistent variable names."""
    if not results or not query: return []
    model_name = settings.get('rag_ranking_model_name','all-MiniLM-L6-v2'); similarity_threshold = settings.get('rag_similarity_threshold',0.30); ranking_model = _get_sentence_transformer_model(model_name)
    if not ranking_model or not _util_module: 
        logger.warning(f"Rank model '{model_name}' unavailable."); 
        f=[r for r in results if r.get('text_snippet')]; return f[:max_results_to_return] # Use full name
    logger.info(f"Ranking {len(results)} using '{model_name}'(Th:{similarity_threshold:.2f})"); 
    snippets = [r.get('text_snippet','') for r in results]; 
    valid_indices = [i for i,s in enumerate(snippets) if s]; 
    if not valid_indices: 
        return []; 
    valid_snippets = [snippets[i] for i in valid_indices]; valid_results = [results[i] for i in valid_indices]
    try:
        start = time.time(); hits = _util_module.semantic_search(ranking_model.encode(query,convert_to_tensor=True), ranking_model.encode(valid_snippets,convert_to_tensor=True),top_k=len(valid_indices))[0]; logger.debug(f"Semantic search: {time.time()-start:.2f}s")
        ranked_with_scores = []; logger.debug("--- Scores ---"); [(r.update({'score':h['score']}),ranked_with_scores.append(r),logger.debug(f" {h['score']:.3f}|{r.get('source','?')[0]}|{r.get('title','N/A')[:60]}")) for h in hits if(r:=valid_results[h['corpus_id']])]; passed=[r for r in ranked_with_scores if r['score']>=similarity_threshold]; logger.info(f"{len(passed)} passed th {similarity_threshold:.2f}(of {len(valid_results)})"); passed and [logger.debug("--- Passed ---"),[logger.debug(f" {r['score']:.3f}|{r.get('title','N/A')[:60]}") for r in passed]]; final=passed[:max_results_to_return]; logger.info(f"Return top {len(final)}"); return final # Use full name
    except Exception as e: logger.error(f"Rank err: {e}"); logger.warning("Fallback unranked."); return valid_results[:max_results_to_return] # Use full name

