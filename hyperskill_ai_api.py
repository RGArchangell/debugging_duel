import requests
import json


def map_gpt_title(title: str):
    return title.strip('"')


def get_system_prompt_from_messages(messages):
    """Extracts system prompts from messages
    :param messages: list of messages with fields `role` and `content`
    :return: system_prompt object with fields `role` and `content`, user_prompts list of messages.
    """
    system_prompts = [message for message in messages if message["role"] == "system"]
    system_prompt_content = "\n".join(message["content"] for message in system_prompts)
    system_prompt = {"role": "system", "content": system_prompt_content}

    user_prompts = [message for message in messages if message["role"] != "system"]
    return system_prompt, user_prompts


class HyperskillAIAPI():
    __URL__ = "https://ai-provider.aks-hs-dev.int.hyperskill.org/chat-completion"

    def __init__(self, api_key, model, provider = None):
        self.__api_key = api_key
        self.__model = model
        self.__provider = provider

    def get_chat_completion(self, messages):
        system_prompt, user_prompts = get_system_prompt_from_messages(messages)
        system_message = system_prompt["content"]
        payload_dict = {"messages": user_prompts, "model": self.__model}
        if len(system_message) > 0:
            payload_dict["system"] = system_message

        if self.__provider is not None:
            payload_dict["provider"] = self.__provider
        payload = json.dumps(payload_dict)

        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + self.__api_key,
        }

        response = requests.post(self.__URL__, headers=headers, data=payload)
        response.raise_for_status()
        return response.json()["content"]
