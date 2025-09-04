# OpenAPI Audit Report

- ## verbs in path
- [PATH /createUser] avoid verbs in URL; use resource nouns + HTTP methods
- ## plural collections
- [GET /user] collection names should be plural (e.g., '/users')
- [GET /search] collection names should be plural (e.g., '/users')
- ## JSON key style
- JSON keys mix styles: camelCase (1) and snake_case (1). Choose one convention.
- ## parameter name style
- Parameter names mix styles: camelCase (1) and snake_case (1). Use one convention across API.
- ## versioning
- No version segment found in servers[].url; prefer `/.../v1` style.
