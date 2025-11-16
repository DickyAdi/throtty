# Throtty

A flexible and powerful rate limiting library for ASGI applications like FastAPI and Starlette.

## Features

- 🚀 **Easy Integration** - Simple decorator-based API for quick setup
- 🔄 **Multiple Algorithms** - Support for sliding window counter, sliding window log, and token bucket
- 💾 **Flexible Storage** - In-memory storage or Redis for distributed systems
- 🎯 **Pattern Matching** - Regex and wildcard support for flexible path matching
- 🔑 **Custom Key Extraction** - Rate limit by IP, user ID, API key, or any custom logic
- 🌐 **Distributed Ready** - Redis backend for multi-server deployments
- 📊 **Informative Headers** - Standard rate limit headers in responses

## Installation

```bash
pip install throtty
```

## Quick Start

```python
from fastapi import FastAPI
from throtty.core import Throtty, rule

# Initialize Throtty with in-memory storage
limiter = Throtty()

app = FastAPI()
limiter.install(app)

# Apply rate limit: 10 requests per minute
@app.get("/api/limited")
@rule("/api/limited", "10/60")
async def limited_endpoint():
    return {"message": "This endpoint is rate limited"}
```

## Basic Usage

### 1. Initialize Throtty

**In-Memory Storage (Single Server)**

```python
from throtty.core import Throtty

limiter = Throtty()
```

**Redis Storage (Distributed/Multi-Server)**

```python
# Using Redis DSN
limiter = Throtty(redis_dsn="redis://localhost:6379/0")

# Using existing Redis client
from redis import Redis
redis_client = Redis(host='localhost', port=6379, db=0)
limiter = Throtty(redis=redis_client)

# Using Redis connection pool
from redis import ConnectionPool
pool = ConnectionPool(host='localhost', port=6379, db=0)
limiter = Throtty(redis_pool=pool)
```

### 2. Install Middleware

```python
from fastapi import FastAPI

app = FastAPI()
limiter.install(app)  # Must be called to activate rate limiting
```

### 3. Add Rate Limiting Rules

**Using Decorators (Recommended)**

```python
from throtty.core import rule

@app.get("/api/users")
@rule("/api/users", "100/60")  # 100 requests per minute
async def get_users():
    return {"users": []}
```

**Using add_rule Method**

```python
# Add rules programmatically
limiter.add_rule("/api/posts", limit=50, window=60)
limiter.add_rule("/api/comments", limit=200, window=3600)
```

## Advanced Usage

### Multiple Rate Limits

Apply multiple rate limits to the same endpoint (all must pass):

```python
@app.post("/api/data")
@rule("/api/data", "10/60;100/3600")  # 10/min AND 100/hour
async def post_data():
    return {"status": "created"}
```

### Path Patterns

**Exact Match**

```python
@rule("/api/users", "100/60")  # Only matches /api/users
```

**Wildcard Match**

```python
@rule("/api/v1/*", "1000/3600")  # Matches /api/v1/users, /api/v1/posts, etc.
```

**Regex Pattern**

```python
@rule("^/api/v[0-9]+/.*", "2000/3600")  # Matches /api/v1/..., /api/v2/..., etc.
```

### Custom Key Extraction

Rate limit by user ID instead of IP address:

```python
def extract_user_id(host, headers):
    """Extract user ID from authorization header"""
    user_id = headers.get('x-user-id', 'anonymous')
    return f"user:{user_id}"

@app.get("/api/profile")
@rule("/api/profile", "50/3600", key_func=extract_user_id)
async def get_profile():
    return {"profile": "data"}
```

**Global Key Extractor**

Set a default key extractor for all rules:

```python
def extract_api_key(host, headers):
    api_key = headers.get('x-api-key', 'anonymous')
    return f"apikey:{api_key}"

limiter.set_key_extractor(extract_api_key)

# All rules will now use API key unless overridden
@app.get("/api/data")
@rule("/api/data", "100/60")  # Uses global extractor
async def get_data():
    return {"data": []}
```

### Rate Limiting Algorithms

Choose the algorithm that best fits your needs:

```python
# Sliding Window Counter (default) - Best balance of accuracy and performance
limiter = Throtty(algorithm="slidingwindow_counter")

# Sliding Window Log - Most accurate, higher memory usage
limiter = Throtty(algorithm="slidingwindow_log")

# Token Bucket - Allows bursts, smooth rate limiting
limiter = Throtty(algorithm="token_bucket")
```

**Algorithm Comparison:**

| Algorithm              | Accuracy | Memory | Performance | Bursts |
| ---------------------- | -------- | ------ | ----------- | ------ |
| Sliding Window Counter | High     | Low    | Excellent   | No     |
| Sliding Window Log     | Highest  | High   | Good        | No     |
| Token Bucket           | Medium   | Low    | Excellent   | Yes    |

## Response Headers

When a request is rate limited (HTTP 429), Throtty includes informative headers:

```http
HTTP/1.1 429 Too Many Requests
Content-Type: application/json
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 0
X-RateLimit-Reset-At: 1699564800
Retry-After: 45

"Rate limit exceeded"
```

**Header Descriptions:**

- `X-RateLimit-Limit` - Maximum requests allowed in the time window
- `X-RateLimit-Remaining` - Requests remaining in current window
- `X-RateLimit-Reset-At` - Unix timestamp when the rate limit resets
- `Retry-After` - Seconds to wait before retrying

## Complete Example

```python
from fastapi import FastAPI, Header
from throtty.core import Throtty, rule
from typing import Optional

# Initialize with Redis for distributed systems
limiter = Throtty(
    redis_dsn="redis://localhost:6379/0",
    algorithm="slidingwindow_counter"
)

app = FastAPI()
limiter.install(app)

# Custom key extractor for user-based limiting
def extract_user(host, headers):
    user_id = headers.get('authorization')
    if user_id:
        return f"user:{user_id}"
    return f"ip:{host}"

limiter.set_key_extractor(extract_user)

# Public endpoint - strict limit
@app.get("/api/public")
@rule("/api/public", "10/60")  # 10 requests per minute
async def public_endpoint():
    return {"message": "Public data"}

# Authenticated endpoint - higher limit
@app.get("/api/users")
@rule("/api/users", "100/60;1000/3600")  # 100/min AND 1000/hour
async def get_users(authorization: Optional[str] = Header(None)):
    return {"users": ["user1", "user2"]}

# Premium endpoint - custom key function
def premium_key(host, headers):
    tier = headers.get('x-subscription-tier', 'free')
    user = headers.get('x-user-id', 'anonymous')
    return f"{tier}:{user}"

@app.get("/api/premium")
@rule("/api/premium", "1000/3600", key_func=premium_key)
async def premium_endpoint():
    return {"data": "premium content"}

# Wildcard - all v1 endpoints share limit
@app.get("/api/v1/posts")
@app.get("/api/v1/comments")
@rule("/api/v1/*", "5000/3600")
async def v1_endpoints():
    return {"version": "v1"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

## Configuration Options

### Throtty Initialization

```python
Throtty(
    redis=None,                    # Redis client instance
    redis_pool=None,               # Redis connection pool
    redis_dsn=None,                # Redis DSN string
    max_connections=10,            # Max connections in pool
    algorithm="slidingwindow_counter"  # Rate limiting algorithm
)
```

### Adding Rules

```python
limiter.add_rule(
    path="/api/endpoint",          # Endpoint path (supports regex)
    limit=100,                     # Max requests
    window=60,                     # Time window in seconds
    key_func=None                  # Optional key extractor
)
```

### Rule Decorator

```python
@rule(
    path="/api/endpoint",          # Endpoint path
    str_rule="10/60;100/3600",    # "limit/window" format
    key_func=None                  # Optional key extractor
)
```

## Common Patterns

### Per-User Rate Limiting

```python
def by_user_id(host, headers):
    return f"user:{headers.get('x-user-id', host)}"

@app.get("/api/user-data")
@rule("/api/user-data", "100/3600", key_func=by_user_id)
async def user_data():
    return {"data": []}
```

### API Key Based Limiting

```python
def by_api_key(host, headers):
    api_key = headers.get('x-api-key', 'anonymous')
    return f"apikey:{api_key}"

limiter.set_key_extractor(by_api_key)
```

### Tiered Rate Limiting

```python
def tiered_limit(host, headers):
    tier = headers.get('x-tier', 'free')
    user = headers.get('x-user-id', host)
    return f"{tier}:{user}"

@app.get("/api/tiered")
@rule("/api/tiered", "10/60", key_func=tiered_limit)  # Free tier
async def tiered_endpoint():
    return {"data": []}
```

### Version-Specific Limits

```python
# v1 endpoints - lower limit
limiter.add_rule("/api/v1/*", limit=100, window=3600)

# v2 endpoints - higher limit
limiter.add_rule("/api/v2/*", limit=1000, window=3600)
```

## Best Practices

1. **Initialize Early** - Create Throtty instance before defining routes
2. **Install Middleware** - Always call `limiter.install(app)` to activate rate limiting
3. **Use Redis for Production** - In-memory storage only suitable for single-server setups
4. **Match Paths Carefully** - Ensure decorator paths match route paths
5. **Test Limits** - Verify rate limits work as expected in staging
6. **Monitor Usage** - Track rate limit hits to adjust limits appropriately
7. **Graceful Degradation** - Handle rate limit errors in client applications
8. **Document Limits** - Inform API users about rate limits in documentation

## Error Handling

When rate limits are exceeded, Throtty returns a 429 response:

```python
from fastapi import Request
from fastapi.responses import JSONResponse

@app.exception_handler(429)
async def rate_limit_handler(request: Request, exc):
    return JSONResponse(
        status_code=429,
        content={
            "error": "Rate limit exceeded",
            "message": "Please try again later"
        }
    )
```

## Performance Considerations

- **In-Memory Storage**: Fast but not shared across servers
- **Redis Storage**: Slight network overhead but enables distributed limiting
- **Algorithm Choice**:
  - Use `slidingwindow_counter` for best performance
  - Use `slidingwindow_log` for highest accuracy
  - Use `token_bucket` for burst tolerance

## Troubleshooting

### Rate Limiting Not Working

1. Ensure `limiter.install(app)` is called
2. Verify path in `@rule` matches route path
3. Check Throtty is initialized before using `@rule`

### Redis Connection Issues

```python
# Test Redis connection
limiter = Throtty(redis_dsn="redis://localhost:6379/0")
# Check Redis is running: redis-cli ping
```

### Rules Not Matching

```python
# Debug rule matching
rule = limiter._find_match_rule("/api/users")
print(f"Matched rule: {rule}")
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

MIT License - see LICENSE file for details

## Support

- **Issues**: [GitHub Issues](https://github.com/dickyadi/throtty/issues)
- **Discussions**: [GitHub Discussions](https://github.com/dickyadi/throtty/discussions)

## Changelog

### v0.0.1

- Initial release
- Support for FastAPI
- In-memory and Redis storage
- Multiple rate limiting algorithms
- Flexible path matching with regex
- Custom key extraction functions
