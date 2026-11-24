# Changelog

## [1.1.1](https://github.com/nullthrone/governance/compare/v1.1.0...v1.1.1) (2026-11-24)


### Bug Fixes

* skip publish-secrets in the CI audit, which the app token cannot read ([#24](https://github.com/nullthrone/governance/issues/24)) ([909be11](https://github.com/nullthrone/governance/commit/909be1197f65f8cf4ff9d6f12a79f20e59e4a43a))

## [1.1.0](https://github.com/nullthrone/governance/compare/v1.0.0...v1.1.0) (2026-11-24)


### Features

* add organizations elunea and cinewright ([6f1d6c3](https://github.com/nullthrone/governance/commit/6f1d6c3e8a5dd0e98c960f1bf97f1b0d70cbe4ed))
* add organizations elunea and cinewright ([3173684](https://github.com/nullthrone/governance/commit/317368402d5939115aa388cd89a853e550dd2387))


### Bug Fixes

* describe the real feedback path in candidate PRs ([#23](https://github.com/nullthrone/governance/issues/23)) ([6f2ecf5](https://github.com/nullthrone/governance/commit/6f2ecf55c695ffa5266b12a60d744fa84bfd6139)), closes [#19](https://github.com/nullthrone/governance/issues/19)
* let owner PRs to protected paths pass the review ([#14](https://github.com/nullthrone/governance/issues/14)) ([d9b120f](https://github.com/nullthrone/governance/commit/d9b120fa2f75e9c4d4e2379d5fb33f479add2dc9))
* open no release candidate for sync merge commits ([#21](https://github.com/nullthrone/governance/issues/21)) ([c89a452](https://github.com/nullthrone/governance/commit/c89a4525d0aa3d7c62977682a0e2e3c4c94e730c)), closes [#17](https://github.com/nullthrone/governance/issues/17)
* release in-progress when the roadmap run ends without a PR ([#22](https://github.com/nullthrone/governance/issues/22)) ([b60bb8c](https://github.com/nullthrone/governance/commit/b60bb8cc5187bd4208fc213e48500aac1ca2e9e1)), closes [#18](https://github.com/nullthrone/governance/issues/18)
* repair issues found in the first onboarding run ([#12](https://github.com/nullthrone/governance/issues/12)) ([d3d7ccd](https://github.com/nullthrone/governance/commit/d3d7ccdab698d9d0d8486992a363f5c6b4e0f35f))
* **security:** pass named secrets to the deploy workflow ([#13](https://github.com/nullthrone/governance/issues/13)) ([ca9eb90](https://github.com/nullthrone/governance/commit/ca9eb90143f96eed2f9dc782da8633c59156a073))
* write plain vX.Y.Z release tags and accept component-prefixed ones ([#20](https://github.com/nullthrone/governance/issues/20)) ([0c7a888](https://github.com/nullthrone/governance/commit/0c7a888c56a448763bf6feb3cc16a5db513d7fb2)), closes [#16](https://github.com/nullthrone/governance/issues/16)

## 1.0.0 (2026-11-22)


### Features

* add governance plugin marketplace ([91cf493](https://github.com/nullthrone/governance/commit/91cf493758526e15ae2ab80476de51104fc25d0e))
* add governance-audit, detect-profile and install tooling ([a276c50](https://github.com/nullthrone/governance/commit/a276c50b5368e65a29c49cdb60df5a87b9315ec2))
* add organization .github content and project template ([71625cd](https://github.com/nullthrone/governance/commit/71625cd577979c77c83eb2ff377a6b89070e9c91))
* add PO inbox auto-add ([05cef8c](https://github.com/nullthrone/governance/commit/05cef8c68d842398bca7498dcd4ba1f157cc9f7f))
* add reusable workflows and thin callers ([29d9280](https://github.com/nullthrone/governance/commit/29d9280994fa3931feebcc1e78f4b0ad6a707be2))
* add ruleset templates, label taxonomy and label sync ([37b9c39](https://github.com/nullthrone/governance/commit/37b9c39fdd919a75ad0103d95a81c181d5323700))
* build governance layer (plugin marketplace, reusable workflows, audit tooling) ([8deabf0](https://github.com/nullthrone/governance/commit/8deabf0133cfda872f0c0075dcda47c53f8c0ac6))


### Bug Fixes

* handle a missing scorecard binary in governance-audit ([073d8cc](https://github.com/nullthrone/governance/commit/073d8cc92c8421837ea129fddbd35db75edb7823))
* harden PR gates, releases and the audit against bypasses ([27fcac4](https://github.com/nullthrone/governance/commit/27fcac4343b75d20532be87b63104c05cc0b08ff))
* let the org .github sync initialize empty repositories ([1c2e4e5](https://github.com/nullthrone/governance/commit/1c2e4e5a183d5fe04bd7afd908fec5d4d1664daf))
* let the org .github sync initialize empty repositories ([cec6c57](https://github.com/nullthrone/governance/commit/cec6c57ca700fa71fd775f5f0570a7c8e04b73cf))
