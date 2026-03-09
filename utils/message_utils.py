def extract_message(data):

    if not (data.get('entry') and data['entry']):
        return None

    changes = data['entry'][0]['changes'][0]
    value = changes.get('value', {})

    if 'messages' not in value:
        return None

    message = value['messages'][0]

    phone = message.get("from")
    message_type = message.get("type")

    text = ""
    payload = ""

    if message_type == "text":
        text = message.get("text", {}).get("body", "").lower().strip()

    elif message_type == "button":
        payload = message.get("button", {}).get("payload", "")
        text = message.get("button", {}).get("text", "").lower().strip()

    return {
        "phone": phone,
        "text": text,
        "payload": payload,
        "type": message_type
    }
