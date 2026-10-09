# Examples

These are the real files from
[`examples/`](https://github.com/torbenfreise/h2pcontrol/tree/main/examples), included
verbatim at build time — they cannot drift from the repository.

## The starter

Written to `experiments/ramp.py` by `h2pcontrol init`. Needs no hardware.

```python
--8<-- "src/h2pcontrol/controller/_starter.py"
```

## Sine trace

A `LINE` view: the curve is replaced each shot.

```python
--8<-- "examples/example_sine_trace.py"
```

## Sine series

A `SERIES` view: scalar points accumulate across shots.

```python
--8<-- "examples/example_sine_series.py"
```

## MCC DAQ

Reading a real device server.

```python
--8<-- "examples/mccdaq_example.py"
```

## Device stubs

```python
--8<-- "examples/example_h2p.py"
```

## PicoScope

```python
--8<-- "examples/example_picoscope.py"
```
