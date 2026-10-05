# Changelog

## 0.2.0

- `messages.send()` accepts `cc` and `bcc` (lists of addresses or `Name <address>`) besides `to`,
  in the synchronous and the asynchronous client. `to`, `cc` and `bcc` together count against the
  plan's recipient maximum; every copy shows all the `to` and all the `cc`, and a `bcc` address
  appears only on its own copy.
- `to` also accepts `Name <address>`.
- `messages.get()` returns `type` (`to`, `cc` or `bcc`) and `name` for each recipient.
- Requires Duva API behavior of 2026-10-05 or later: recipients of one message now see each other
  (before, each copy showed only its own recipient). Send one message per recipient, or use `bcc`,
  when addresses must not be visible to one another.

## 0.1.0

- First release.
