# Changelog

## 0.5.0 — 2026-10-11
- Replace proxy identity proof with scrypt password hashing, signed process-local sessions, principal proofs, and explicit revocation.
- Keep credentials and sessions in memory only; no persistent session table.

## 0.4.0 — 2026-10-11
- Sign and validate ordinary-user proofs while retaining the owner-admin proxy checks.

## 0.3.0
- Move permission and notebook visibility policies into auth-facade.

## 0.2.0
- Add verified-principal role inspection for auth-facade.

## 0.1.0
- Extract common authentication primitives.
