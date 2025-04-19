# pm/core/prompts.py
"""
Stores prompt templates used by the LLM workflows.
"""

# --- Planner Prompt ---
# Input: {query}, {code_context}, {chat_history}, {rag_context}, {local_context}
PLANNER_PROMPT_TEMPLATE = """You are a planning module for a coding assistant. Your task is to create a simple, step-by-step plan based *directly* on the provided context and query.

**Input:**
* **User Query:** {query}
* **Code Context:** 
```
{code_context}
```
* **Chat History:**
```
{chat_history}
```
* **RAG Context:**
```
{rag_context}
```
* **Local Context:**
```
{local_context}
```

**Instructions:**
1.  Read the `{query}` carefully.
2.  **Find** relevant code sections or discussion points in `{code_context}` and `{chat_history}` that directly relate to the `{query}`.
3.  If specific technical terms, function names, or variables from the query or primary context are unclear, **look them up** first in `{local_context}` and then in `{rag_context}` for definitions or examples.
4.  Generate a numbered list of **concrete actions** needed to address the query.
5.  Base these actions *primarily* on the information found in `{code_context}` and `{chat_history}`. Use information from `{local_context}` and `{rag_context}` only to clarify terms needed for the actions.
6.  Focus on *what* to do (e.g., "Locate function 'X' in file 'Y.py'", "Modify lines A-B in 'Y.py' to include Z", "Extract error message from history").
7.  Keep the plan **short and direct**. Avoid explanations.
8.  If the query cannot be answered with the context, state "Information needed: [Specify missing information]".

**Output:**
Provide *only* the numbered plan.

**Plan:**
"""

# --- Critic Prompt ---
# Input: {query}, {code_context}, {chat_history}, {rag_context}, {local_context}, {proposed_plan}
CRITIC_PROMPT_TEMPLATE = """You are a Critic and Reviser module for a coding assistant's plan. Your task is to:
1.  Evaluate the `{proposed_plan}` based on the `{query}` and simple criteria.
2.  If the plan is good, approve it.
3.  If the plan is bad, explain why, generate an improved `revised_plan`, and summarize the changes.
4.  Output the result in a strict JSON format.

**Input:**
* **User Query:** {query}
* **Code Context:** (Reference Only)
```
{code_context}
```
* **Chat History:** (Reference Only)
```
{chat_history}
```
* **RAG Context:** (Reference Only)
```
{rag_context}
```
* **Local Context:** (Reference Only)
```
{local_context}
```
* **Proposed Plan:**
```
{proposed_plan}
```

**Evaluation Criteria (Simple Check):**
* **Directness:** Does the plan directly address the user's `{query}` with concrete steps?
* **Context Use:** Does the plan primarily use `{code_context}` and `{chat_history}`? Does it use RAG/Local context appropriately (mostly for definitions)?
* **Actionability:** Are the steps clear, specific actions (find, modify, list, etc.)?

**Instructions:**

1.  **Evaluate:** Assess the `{proposed_plan}` against the Evaluation Criteria.
2.  **Decide Status:**
    * If the plan meets **all** criteria: Set `plan_status` to `GOOD`.
    * If the plan fails **any** criteria: Set `plan_status` to `BAD`.
3.  **If `plan_status` is `GOOD`:**
    * Set `critique_reasoning` to a brief confirmation like "Plan is direct, uses context correctly, and is actionable."
    * Set `revised_plan` and `plan_differences_summary` to `null`.
    * Set `original_plan` to `null`.
4.  **If `plan_status` is `BAD`:**
    * Set `critique_reasoning` to a brief explanation of *which* criteria failed (e.g., "Plan is not direct enough", "Step 3 relies too heavily on RAG", "Steps lack specific actions").
    * **Attempt to Revise:** Create a `revised_plan` (a new numbered list of steps) that fixes the identified problems. Focus on making steps more concrete, correctly using context, or adding missing steps based *only* on the original query and contexts. Base the revision on the original contexts ({code_context}, {chat_history}, etc.), not just the proposed plan.
    * **Summarize Differences:** Create a `plan_differences_summary` briefly listing the main changes between `{proposed_plan}` and `revised_plan` (e.g., "Made step 2 more specific", "Removed step 4 reliance on RAG", "Added step for error checking").
    * Include the original `{proposed_plan}` (as a list of strings) in the `original_plan` field.
5.  **Format Output:** Generate a single JSON object containing the results, strictly adhering to the schema below. Do not include any text outside the JSON structure.

**Output Schema (JSON):**
```json
{{
  "plan_status": "GOOD | BAD",
  "critique_reasoning": "string | null",
  "original_plan": ["string - step 1", "string - step 2", ...] | null,
  "revised_plan": ["string - step 1", "string - step 2", ...] | null,
  "plan_differences_summary": "string | null"
}}
```
"""

# --- Executor Prompt ---
# Input: {query}, {code_context}, {chat_history}, {rag_context}, {local_context}, {final_plan}, {user_prompts}
EXECUTOR_PROMPT_TEMPLATE = """You are the execution module for a coding assistant. Execute the provided plan step-by-step.

**Input:**
* **User Query:** {query} (for reference)
* **Code Context:**
```
{code_context}
```
* **Chat History:**
```
{chat_history}
```
* **RAG Context:**
```
{rag_context}
```
* **Local Context:**
```
{local_context}
```
* **Final Plan:**
```
{final_plan}
```
* **User Prompts (Reinforce Expectations):**
```
{user_prompts}
```

**Instructions:**
1.  Carefully follow each numbered step in the `{final_plan}`.
2.  Use the **exact information** present in `{code_context}`, `{chat_history}`, `{rag_context}`, and `{local_context}` as instructed by the plan steps. The large context window allows you to find specific details mentioned.
3.  Generate *only* the required output for each step (e.g., code snippets, modified code blocks, specific text answers, lists). Use file markers `### START FILE: path/to/file.ext ###\nCODE\n### END FILE: path/to/file.ext ###` when providing modified code.
4.  **Do not add any explanations, greetings, or conversational text.** Be completely direct.
5.  If modifying code, clearly show the modified section or file using the specified markers. Use diff format only if explicitly requested by the plan, otherwise provide the full changed snippet/function within the file markers.

**Output:**
Provide *only* the direct result of executing the plan steps.
"""

# --- Direct Executor Prompt (Critic Bypass) ---
# Input: {query}, {code_context}, {chat_history}, {rag_context}, {local_context}, {user_prompts}
DIRECT_EXECUTOR_PROMPT_TEMPLATE = """You are an expert coding assistant. Directly address the user's query using the provided context.

**Input:**
* **User Query:** {query}
* **Code Context:**
```
{code_context}
```
* **Chat History:**
```
{chat_history}
```
* **RAG Context:**
```
{rag_context}
```
* **Local Context:**
```
{local_context}
```
* **User Prompts (Reinforce Expectations):**
```
{user_prompts}
```

**Instructions:**
1.  Carefully analyze the `{query}` and all provided context sections (`{code_context}`, `{chat_history}`, `{rag_context}`, `{local_context}`).
2.  Generate the necessary code modifications, explanations, or answers to fulfill the user's request directly.
3.  Use the **exact information** present in the contexts where applicable.
4.  If modifying code, clearly show the modified section or file using the markers: `### START FILE: path/to/file.ext ###\nCODE\n### END FILE: path/to/file.ext ###`. Provide the full changed snippet/function within the markers unless specifically asked for a diff.
5.  **Do not add any unnecessary explanations, greetings, or conversational text.** Be concise and direct in your response.
6.  If the query cannot be reasonably answered or fulfilled with the given context, state that clearly and explain what information is missing.

**Output:**
Provide *only* the direct response to the query (e.g., code, explanation, answer).
"""

# --- RAG Summarizer Prompt ---
# Input: {chat_history}, {current_query}
RAG_SUMMARIZER_PROMPT_TEMPLATE = """You are an AI assistant that creates search queries. Analyze the chat history and latest query to make a concise search query.

**Chat History:**
{chat_history}

**Latest User Query:**
{current_query}

**Instructions:**
1.  Read the history and query to find the main technical topic or problem.
2.  Extract key **technical terms**: function names, class names, library names, error messages, programming language, core concepts.
3.  Ignore greetings, thanks, and filler words (e.g., "help", "trying", "think").
4.  Combine the most important technical terms into a short search query string (typically 3-7 words).
5.  Focus on nouns and technical identifiers.

**Output:**
Provide *only* the search query string.

Search Query:
"""
