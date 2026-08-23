# Events and Persistence

## Persistent files

`config.json` is device configuration.

`events.json` is runtime scheduler data and contains both events and the event
log. Firmware upgrades do not replace either file.

## Event file versioning

`events.json` has a top-level file schema version. Each event record also has a
`record_version`.

Older event records are upgraded through sequential migration functions until
they reach the version supported by the installed firmware.

The current event schema includes:

- Name.
- Enabled state.
- Days of week.
- Time.
- Action.
- Relay number where applicable.
- Minimum and maximum temperature.
- Rain-block opt-in.
- Wind-block opt-in.
- Skip-next state.
- GET URL settings.

## Actions

Supported actions are:

- Relay On.
- Relay Off.
- All Relays On.
- All Relays Off.
- GET URL.

GET URL responses may specify a relay by name or number and the relay state to
apply.

## Skip behavior

A scheduled event is not considered skipped merely because its day or time did
not match.

A log entry with status `skipped` is created when the day and time did match but
execution was blocked by a configured condition, including:

- Temperature bounds.
- Recent-rain blocking.
- High-wind blocking.
- Skip Next.

## Skip Next

`skip_next` is a one-shot operational flag for an existing event.

It is not offered during event creation and new events always begin with:

```json
"skip_next": false
```

When enabled:

1. The next scheduled occurrence is shown in **Next 3 Events** as
   `WILL BE SKIPPED`.
2. When that occurrence's day and time match, the action is not executed.
3. A skip is written to the event log.
4. `skip_next` is automatically reset to `false`.
5. Future recurrences execute normally unless another skip condition applies.

## Manual relay actions

Manual relay changes made through the controller/API are also written to the
event log with status `manual`.
