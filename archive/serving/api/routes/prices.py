from fastapi import APIRouter

router = APIRouter()

@router.get('/health')
def health():
    return {'prices': 'healthy'}

@router.get('/')
def list_prices(limit: int = 10):
    return {'msg': 'placeholder: return latest prices', 'limit': limit}
