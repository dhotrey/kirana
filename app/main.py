import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

app = FastAPI()


@app.get("/")
def hello():
    return "Hello World!"


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
