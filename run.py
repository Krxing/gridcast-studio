import os

import uvicorn
from dotenv import load_dotenv

load_dotenv()

if __name__ == '__main__':
    uvicorn.run('backend.main:app', host=os.environ.get('APP_HOST', '127.0.0.1'),
                port=int(os.environ.get('APP_PORT', '8000')), workers=1, proxy_headers=False)
