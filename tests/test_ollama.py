import ollama
from loguru import logger

def list_ollama_models_direct_test():
    logger.info("Directly testing ollama.list() parsing...")
    try:
        response = ollama.list()
        logger.info("Raw response type: {}, content: {}", type(response), response)

        models_list = []
        if isinstance(response, dict):
            models_list = response.get('models', [])
        elif hasattr(response, 'models'):
            models_list = getattr(response, 'models', [])
        else:
            logger.error("Response is not dict and has no 'models' attribute.")
            return

        if not isinstance(models_list, list):
            logger.error(f"Response 'models' is not a list: {type(models_list)}")
            return

        names = []
        for i, item in enumerate(models_list):
            name = None
            item_type = type(item).__name__
            logger.info("Processing item {} type {}: {}", i, item_type, item)

            # Prioritize getattr based on logs showing Model(model=...)
            if hasattr(item, 'model'):
                name_attr = getattr(item, 'model', None)
                if isinstance(name_attr, str) and name_attr:
                    name = name_attr
                    logger.info("--> Extracted name via getattr: {}", name)
                else:
                    logger.warning(f"Item {i} has 'model' attribute but value is not a non-empty string: type={type(name_attr)}, value={name_attr!r}")

            # Fallback to dict access only if getattr didn't work
            elif isinstance(item, dict):
                logger.info("Item {} is dict, checking 'model' key...", i)
                name_key = item.get('model')
                if isinstance(name_key, str) and name_key:
                    name = name_key
                    logger.info("--> Extracted name via dict.get('model'): {}", name)
                else:
                    logger.warning(f"Item {i} dict missing 'model' key or value not string.")
                    # Optional: check for 'name' as secondary fallback for dicts?
                    name_key_fallback = item.get('name')
                    if isinstance(name_key_fallback, str) and name_key_fallback:
                         name = name_key_fallback
                         logger.warning(f"--> Used 'name' key fallback for dict item {i}: {name}")

            else:
                 logger.warning(f"Unexpected item type (not object with 'model' or dict) at index {i}: {item_type}")

            if name:
                names.append(name)
            else:
                 logger.warning(f"!! Failed to extract valid model name from item at index {i}: {item}")

        logger.info("Final extracted names: {}", sorted(names))

    except Exception as e:
        logger.exception("Error during direct test: {}", e)

if __name__ == "__main__":
    # Configure logger for direct test output
    import sys
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    list_ollama_models_direct_test()
