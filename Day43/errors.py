class AppError(Exception):
    def __init__(self, message : str, status_code : int = 500):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        
class ConfigurationError(AppError):
    def __init__(self, message : str):
        super().__init__(message, status_code=500)
        
class DataStoreError(AppError):
    def __init__(self, message: str):
        super().__init__(message, status_code=500)

class ExternalServiceError(AppError):
    """The AI provider failed. `retryable` says whether trying again can help (timeouts, 429, 5xx, network)
    or is pointless (bad API key, invalid request, malformed JSON)."""

    def __init__(self, message: str = "External AI service is unavailable", retryable: bool = True):
        super().__init__(message, status_code=503)
        self.retryable = retryable

    
