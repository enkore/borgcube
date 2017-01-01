
import transaction


def transaction_middleware(get_response):
    """
    Calls `transaction.abort()` before and after obtaining a response.
    """
    def middleware(request):
        transaction.abort()
        response = get_response(request)
        transaction.abort()
        return response
    return middleware
