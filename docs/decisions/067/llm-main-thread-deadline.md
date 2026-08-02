# LLM main-thread deadline and provider-worker cleanup

## Trigger

The two T8 live attempts reached extractor and then retained provider-side SSL
reads past their configured deadline. R066 process sampling showed the main
workflow waiting while provider workers remained in socket reads. The previous
daemon-thread wrapper returned control but intentionally left the SDK call
alive, so it could not ensure process shutdown.

## Decision

On a POSIX main thread, `LLMClient` now uses `SIGALRM` and `setitimer` to
interrupt the synchronous SDK call itself at the configured deadline. It saves
and restores a pre-existing alarm handler and timer. Non-main callers retain
the bounded daemon-worker fallback because Python only delivers signals to the
main thread.

The original provider transport timeout remains in the LiteLLM request; the
new deadline is the harness-level backstop.

## Offline evidence

Before the change, a blocking completion returned from the daemon wrapper yet
left a `deepresearch-llm-call` thread alive. Two guards now prove main-thread
interruption for an event wait and a sleep, and require no named provider
worker after return. Mutating the main-thread condition to false makes the
no-leftover-worker guard fail. The full offline gate passed after the repair.

## Limitation and next action

This proves local interruption behavior, not a successful paid E2E. Any live
T8 validation after this code change is a new experiment and requires a new
user authorization and preregistration.
