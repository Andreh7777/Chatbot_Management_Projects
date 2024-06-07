from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import redis
import json
import uuid
from configparser import ConfigParser
from apscheduler.schedulers.background import BackgroundScheduler
import httpx

# Load configuration from the file
config = ConfigParser()
config.read('config.ini')

# Initialize the Redis client with parameters from the configuration file
redis_client = redis.Redis(
    host=config.get('DEFAULT', 'redis_host'),
    port=config.getint('DEFAULT', 'redis_port'),
    password=config.get('DEFAULT', 'redis_password')
)

# Initialize the scheduler
scheduler = BackgroundScheduler()

# Define a function to delete messages from the Redis cache
def delete_messages():
    keys = redis_client.keys('*')
    for key in keys:
        redis_client.delete(key)

# Add the delete_messages function to the scheduler
scheduler.add_job(delete_messages, 'interval', hours=1)

# Start the scheduler
scheduler.start()

# Initialize the FastAPI application
app = FastAPI()

# Define the request model for the chat endpoint
class ChatRequest(BaseModel):
    session_id: str = None  # optional session_id
    message: str

# Function to call the API and get a response
async def get_response(messages):
    url = config.get('DEFAULT', 'api_url')
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': f'Bearer {config.get('DEFAULT', 'JWT_TOKEN')}'
    }
    payload = {
        "model": config.get('DEFAULT', 'model'),
        "messages": messages
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()

# Define the chat endpoint
@app.post("/chat/")
async def chat(request: ChatRequest):
    session_id = request.session_id if request.session_id else str(uuid.uuid4())
    message = request.message

    # Retrieve the user's chat history from Redis
    chat_history = redis_client.get(session_id)
    if chat_history is not None:
        chat_history = json.loads(chat_history)
    else:
        chat_history = []

    # Add the user's message to the chat history
    chat_history.append({"role": "user", "content": message})

    # Generate a response using the API
    try:
        API_response = await get_response(chat_history)
        response_content = API_response['choices'][0]['message']['content']
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Add the model's response to the chat history
    chat_history.append({"role": "assistant", "content": response_content})

    # Update the chat history in the Redis database
    redis_client.set(session_id, json.dumps(chat_history))

    # Return the response and the session_id
    return {"response": response_content, "session_id": session_id}
