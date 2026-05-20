from fastapi import FastAPI
from .routes import prices

app = FastAPI(title='PriceTracker API')
app.include_router(prices.router, prefix='/prices')

@app.get('/')
async def root():
    return {'service': 'pricetracker', 'status': 'ok'}
