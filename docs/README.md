# AI Hub Documentation

[English](README.md) | [简体中文](README.zh-CN.md)

## Maintained reader documentation

| Topic | English | Simplified Chinese |
|---|---|---|
| Project introduction | [README](../README.md) | [README](../README.zh-CN.md) |
| Architecture | [Architecture Overview](ARCHITECTURE.md) | [架构总览](ARCHITECTURE.zh-CN.md) |
| Product | [Product Overview](PRODUCT.md) | [产品说明](PRODUCT.zh-CN.md) |
| Roadmap | [Roadmap](ROADMAP.md) | [路线图](ROADMAP.zh-CN.md) |
| Terminology | [Glossary](GLOSSARY.md) | [术语表](GLOSSARY.zh-CN.md) |
| Provider extension | [Provider Specification](PROVIDER_SPEC.md) | [Provider 规范](PROVIDER_SPEC.zh-CN.md) |
| Contributions | [Contributing](../CONTRIBUTING.md) | [贡献指南](../CONTRIBUTING.zh-CN.md) |

## Normative and historical records

These documents remain in their original language. Translating an immutable
decision or review would create a second record that could drift from the
accepted source.

- [Runtime Contract](runtime-contract.md) — normative runtime behavior
- [Architecture Decision Records](adr/) — accepted and proposed decisions
- [External reviews](reviews/) — review prompts and outcomes
- [Provider SDK (legacy guide)](provider_sdk.md) — use the maintained Provider
  Specification first
- [GUI Bridge design history](GUI_BRIDGE_DESIGN.md)
- Version-specific SOPs, scopes, verification reports, and handoff documents

## Language policy

- The unsuffixed maintained filename is English.
- The Simplified Chinese pair uses `.zh-CN.md`.
- Both files include reciprocal language links at the top.
- A change to behavior, commands, version status, or public contracts must update
  both language files in the same pull request.
- Code identifiers, schemas, and command examples remain unchanged between
  languages.
- ADRs, reviews, handoffs, and release artifacts keep their original language.

## Source of truth

Git tags and accepted ADRs are the release source of truth. The package metadata
currently reports `0.0.1`, while the repository release milestone is V1.0.11;
this mismatch is tracked as documentation and packaging maintenance work.
