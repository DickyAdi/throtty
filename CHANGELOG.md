# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Nothing yet.

## [0.0.1] - 2025-11-16

### Added

- Initial release of `throtty`.
- Implemented rate limiting for ASGI (FastAPI/Starlette).
- Added algorithms: sliding window counter, sliding window log, token bucket.
- Added storage backends: in-memory and Redis.
- Added decorator-based API + key extraction logic.
