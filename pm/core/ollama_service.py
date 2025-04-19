# In pm/core/ollama_service.py

from ollama import Client
from loguru import logger

class OllamaService:
    def __init__(self, model: str):
        logger.debug("Initialising OllamaService model=%s", model)
        self.model = model
        # Ensure the client is initialized correctly
        try:
             self.client = Client()
             # Optional: Verify connection if possible, e.g., by listing models
             # self.client.list()
             logger.info("Ollama client initialized.")
        except Exception as e:
             logger.exception(f"Failed to initialize Ollama client: {e}")
             self.client = None # Mark client as invalid

    def stream(self, prompt: str):
        if not self.client:
             logger.error("Ollama client not initialized. Cannot stream.")
             # Optionally yield an error message?
             yield "[Error: Ollama client not initialized]"
             return # Stop execution

        #logger.debug(f"OllamaService stream starting for model {self.model}...")
        try:
            # ---> This is the CORRECT way to call Ollama streaming <---
            stream = self.client.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                stream=True
            )
            # ----------------------------------------------------------

            count = 0
            for chunk in stream:
                # Correct way to get text from Ollama stream chunk
                text = chunk.get("message", {}).get("content", "")
                #logger.debug(f"OllamaService yielding chunk content (type={type(text)}, len={len(text)}): {text!r}")
                if text: # Only yield if there's content
                    #logger.debug(f"Ollama service yielding chunk {count}: {text!r}")
                    yield text
                    count += 1
                # Handle potential 'done' status or errors within the chunk if needed
                if chunk.get('done') and chunk.get('error'):
                     logger.error(f"Ollama stream returned error: {chunk.get('error')}")
                     # You might want to raise an exception or yield an error message here
                     # raise Exception(f"Ollama error: {chunk.get('error')}")

            logger.debug("Ollama service stream finished yielding.")

        except Exception as e:
            logger.error(f"Error within OllamaService stream method: {e}")
            # Re-raise the exception so it's caught by the main thread's error handler
            raise

    # Keep the non-streaming send method as well if you use it elsewhere
    def send(self, prompt: str) -> str:
        if not self.client:
            logger.error("Ollama client not initialized. Cannot send.")
            return "[Error: Ollama client not initialized]"
        try:
            resp = self.client.chat(model=self.model, messages=[{"role": "user", "content": prompt}])
            return resp.get("message", {}).get("content", "")
        except Exception as e:
             logger.error(f"Error during Ollama send: {e}")
             return f"[Error: {e}]"