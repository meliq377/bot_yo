import requests
import base64
import time
from datetime import datetime, timedelta
from decimal import Decimal
import zeep

# YoAI API Key
YOAI_API_KEY = "01945ae0-be7b-704c-a643-bd69dc13e439:95f82b9aa60db092312f5fc6ca4425412f8c544be879446f6cbb35ea9dac9152"

# YoAI API Endpoints
GET_UPDATES_URL = "https://yoai.yophone.com/api/pub/getUpdates"
SEND_MESSAGE_URL = "https://yoai.yophone.com/api/pub/sendMessage"

# Headers for API requests
HEADERS = {
    "Content-Type": "application/json",
    "X-YoAI-API-Key": YOAI_API_KEY,
}

# SOAP client setup for fiat currency rates
WSDL_URL = 'http://api.cba.am/exchangerates.asmx?wsdl'
client = zeep.Client(wsdl=WSDL_URL)

# CoinGecko API URL for cryptocurrency rates
COINGECKO_API = "https://api.coingecko.com/api/v3/simple/price"


def decode_base64(text):
    """
    Decodes a Base64-encoded string into plain text.
    """
    try:
        return base64.b64decode(text).decode("utf-8")
    except Exception as e:
        print(f"Error decoding Base64 text: {e}")
        return text


def get_currency_rate(currency_iso):
    """
    Fetch the exchange rate for a given fiat currency ISO code (e.g., USD, EUR).
    """
    try:
        previous_date = datetime.now() - timedelta(days=1)
        previous_date_str = previous_date.strftime('%Y-%m-%d')

        # Fetch exchange rates from CBA
        response = client.service.ExchangeRatesByDate(previous_date_str)
        rates = response['Rates']['ExchangeRate']

        for rate in rates:
            if rate['ISO'] == currency_iso:
                return Decimal(rate['Rate'])
    except Exception as e:
        print(f"Error fetching currency rate: {e}")
        return None


def get_crypto_rate(crypto_id):
    """
    Fetch the cryptocurrency rate in AMD using CoinGecko API.
    """
    try:
        response = requests.get(
            COINGECKO_API,
            params={"ids": crypto_id, "vs_currencies": "amd"}
        )
        response.raise_for_status()
        data = response.json()
        if crypto_id in data and "amd" in data[crypto_id]:
            return data[crypto_id]["amd"]
        return None
    except Exception as e:
        print(f"Error fetching crypto rate: {e}")
        return None


def get_updates():
    """
    Fetches updates from YoAI.
    """
    try:
        response = requests.post(GET_UPDATES_URL, json={}, headers=HEADERS)
        if response.status_code == 200:
            updates = response.json()
            if updates.get("success") and updates.get("data"):
                return updates["data"]
            else:
                print("No updates available.")
                return []
        elif response.status_code == 204:
            print("No new updates (HTTP 204). Waiting for new messages...")
            return []
        else:
            print(f"Failed to fetch updates. HTTP Status: {response.status_code}, Response: {response.text}")
            return []
    except Exception as e:
        print(f"Error while fetching updates: {e}")
        return []


def send_message(chat_id, text):
    """
    Sends a message to a specific chat ID via YoAI.
    """
    payload = {"to": chat_id, "text": text}
    try:
        response = requests.post(SEND_MESSAGE_URL, json=payload, headers=HEADERS)
        if response.status_code == 200 and response.json().get("success"):
            print(f"Message sent to {chat_id}: {text}")
        else:
            print(f"Failed to send message to {chat_id}: {response.json()}")
    except Exception as e:
        print(f"Error sending message: {e}")


def process_updates():
    """
    Processes updates by decoding messages and sending appropriate responses.
    """
    updates = get_updates()
    if not updates:
        print("No updates to process.")
    for message in updates:
        chat_id = message.get("chatId")
        encoded_text = message.get("text", "")
        sender = message.get("sender", {})
        sender_name = f"{sender.get('firstName', '')} {sender.get('lastName', '')}".strip()

        # Decode the Base64 message text
        text = decode_base64(encoded_text)

        print(f"Processing message: {text} from {sender_name} (Chat ID: {chat_id})")

        # Respond based on the message content
        if text.lower() == "/start":
            response_text = (
                f"Welcome, {sender_name}! 👋\n"
                "I am your Real-Time Rate Bot. Type 'help' for commands or send me a currency/crypto code."
            )
        elif text.lower() == "help":
            response_text = (
                "Available commands:\n"
                "- /start: Start the bot\n"
                "- USD/EUR: Get currency exchange rates\n"
                "- BTC/ETH/FTN: Get cryptocurrency rates\n"
                "- help: Show this help message"
            )
        elif text.upper() in ["USD", "EUR"]:
            # Fetch fiat currency rates
            rate = get_currency_rate(text.upper())
            if rate is not None:
                response_text = f"The real-time exchange rate for {text.upper()} is {rate} AMD."
            else:
                response_text = f"Sorry, I couldn't fetch the exchange rate for {text.upper()}."
        elif text.upper() in ["BTC", "ETH", "DOGE", "FTN"]:
            # Fetch crypto rates
            crypto_id_map = {"BTC": "bitcoin", "ETH": "ethereum", "DOGE": "dogecoin", "FTN": "Fasttoken"}
            crypto_id = crypto_id_map[text.upper()]
            rate = get_crypto_rate(crypto_id)
            if rate is not None:
                response_text = f"The real-time rate for {text.upper()} is {rate} AMD."
            else:
                response_text = f"Sorry, I couldn't fetch the rate for {text.upper()}."
        else:
            response_text = f"Sorry, I didn't understand that. You said: {text}"

        # Send the response back to the user
        send_message(chat_id, response_text)


if __name__ == "__main__":
    print("YoAI Rate Bot is running...")

    # Use polling to fetch updates
    while True:
        process_updates()
        time.sleep(5)
