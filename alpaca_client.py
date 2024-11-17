from alpaca.broker.client import BrokerClient
import os

# Replace with your API key and secret
API_KEY = os.getenv("ALPACA_API")
API_SECRET = os.getenv("ALPACA_SECRET")

# Initialize the broker client
broker_client = BrokerClient(api_key=API_KEY, secret_key=API_SECRET)

def create_account(data):
    try:
        # Send POST request to create an account
        response = broker_client.post("/accounts", json=data)
        print(f"Account created: {response}")
        return response
    except Exception as e:
        print(f"Error creating account: {e}")
        return {"error": str(e)}
