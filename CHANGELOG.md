# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.1] - 2026-04-25

### Added
- Nouveau **Dashboard Live** (accessible via `/dashboard`) avec metrics temps réel et efficacité du cache.
- Design premium et responsive pour le dashboard, aligné sur la charte graphique du site.
- Bouton "Retour au site" sur le dashboard pour une navigation fluide.
- Lien vers le Dashboard direct sur la page d'accueil.

### Fixed
- Correction de la cohérence des versions entre le code, la documentation et le site web.

## [1.0.0] - 2026-04-21

### 🚀 Production Ready (V1.0)
We are extremely proud to announce the **V1.0.0 stable release** of the **FFBB MCP Server**.
This major milestone brings enterprise-grade stability, lightning-fast intelligent caching, and rigorous compliance with the latest Model Context Protocol (MCP) standards. 
Built specifically to empower Large Language Models (LLMs) with deep, contextual real-time data from the French Basketball Federation, this release gives absolute confidence for production workloads.

### Features
- **Intelligent Prompt Directives**: Complete rewrite of the `.prompts` system to provide strict, unambiguous LLM-routing directives. LLMs now automatically self-correct ambiguities via context indices, drastically reducing hallucinations.
- **Enterprise-Grade Caching Strategy**: Split processing and caching for Match/Poule contexts. Dynamic TTL assignments based on live match status ensure real-time accuracy without overwhelming external endpoints.
- **Dual-Transport Layer Architecture**: Fully verified stable support for both `stdio` and `SSE` (Server-Sent Events) MCP transports, adhering strictly to the spec `2025-11-25`.
- **Search Robustness**: Overhauled the Meilisearch integration to correctly handle edge-cases (like JAV - Jeanne d'Arc de Vichy) where local data indexing previously failed.
- **GEO/SEO Optimized Documentation**: Comprehensive optimization of the GitHub Pages documentation and repository README, ensuring maximum discoverability for autonomous agents and human users.

### Fixed
- Addressed multiple critical edge-cases related to incomplete data in regional tournaments.
- Fixed an issue where the application cache was improperly shared between `classement` and `poule` calculations.
- Cleaned up duplicate and legacy code, removing deprecated components for a hardened security model.

### Removed
- Removed legacy HTTP routes that bypassed the core MCP logic. All data should now securely flow directly through the standard MCP protocol.
