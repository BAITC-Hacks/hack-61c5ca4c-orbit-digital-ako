"""One local process, no Node required at runtime."""
import uvicorn

if __name__ == '__main__':
    uvicorn.run('api.main:app', host='127.0.0.1', port=8000, access_log=False)
