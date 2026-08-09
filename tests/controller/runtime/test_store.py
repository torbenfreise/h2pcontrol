from __future__ import annotations

import pickle

import numpy as np
import pandas as pd
import pytest
import tables

from h2pcontrol.controller.framework.experiment import Context, Experiment
from h2pcontrol.controller.framework.parameters import ParamSpec, param
from h2pcontrol.controller.framework.results import Results, ResultSpec, result
from h2pcontrol.controller.runtime.store import RunSchema, RunStore


def _spec(dtype: type, *, unit: str | None = None, description: str | None = None) -> ResultSpec:
    return ResultSpec(dtype=dtype, unit=unit, description=description)


def _schema(
    results: dict[str, ResultSpec] | None = None,
    params: dict[str, ParamSpec] | None = None,
) -> RunSchema:
    return RunSchema(results=results or {}, params=params or {})


def _frame(result_cols: dict, param_cols: dict) -> pd.DataFrame:
    """A production-shaped shot frame with result/params under a MultiIndex."""
    return pd.concat(
        [pd.DataFrame(result_cols), pd.DataFrame(param_cols)],
        axis=1,
        keys=["result", "params"],
    )


def _shot_frame(*, trace=None) -> pd.DataFrame:
    result_cols = {"mean_v": [1.5], "n_samples": [1000]}
    if trace is not None:
        result_cols["trace"] = [trace]
    return _frame(result_cols, {"voltage": [3.3]})


def _shot_schema(*, trace: bool = False) -> RunSchema:
    results = {"mean_v": _spec(float), "n_samples": _spec(int)}
    if trace:
        results["trace"] = _spec(np.ndarray)
    return _schema(results, {"voltage": param(3.3)})


class TestRunMetadata:
    def test_schema_metadata_written_to_root_attrs(self, tmp_path):
        schema = RunSchema(
            results={"reading": _spec(float)},
            params={},
            metadata={"sample_interval_ns": "8.0", "post_samples": "1000"},
        )
        store = RunStore.create(tmp_path, "Exp", schema=schema)
        store.close()
        with tables.open_file(str(store.path)) as f:
            assert f.root._v_attrs["sample_interval_ns"] == "8.0"
            assert f.root._v_attrs["post_samples"] == "1000"

    def test_framework_attrs_win_over_experiment_metadata(self, tmp_path):
        # An experiment key colliding with framework run metadata must not win.
        schema = RunSchema(results={}, params={}, metadata={"experiment_source": "SPOOFED"})
        store = RunStore.create(
            tmp_path, "Exp", schema=schema, attrs={"experiment_source": "real source"}
        )
        store.close()
        with tables.open_file(str(store.path)) as f:
            assert f.root._v_attrs["experiment_source"] == "real source"


class TestRunNumbering:
    def test_first_run_is_one(self, tmp_path):
        store = RunStore.create(tmp_path, "My Experiment", schema=_schema())
        store.close()
        assert store.run_number == 1
        assert store.path == tmp_path / "My Experiment_0001.h5"
        assert store.path.is_file()

    def test_run_number_auto_increments(self, tmp_path):
        RunStore.create(tmp_path, "Exp", schema=_schema()).close()
        RunStore.create(tmp_path, "Exp", schema=_schema()).close()
        store = RunStore.create(tmp_path, "Exp", schema=_schema())
        store.close()
        assert store.run_number == 3
        assert store.path.name == "Exp_0003.h5"

    def test_runs_are_per_experiment(self, tmp_path):
        RunStore.create(tmp_path, "A", schema=_schema()).close()
        store = RunStore.create(tmp_path, "B", schema=_schema())
        store.close()
        assert store.run_number == 1

    def test_gaps_do_not_collide(self, tmp_path):
        RunStore.create(tmp_path, "Exp", schema=_schema()).close()
        tables.open_file(str(tmp_path / "Exp_0007.h5"), mode="w").close()
        store = RunStore.create(tmp_path, "Exp", schema=_schema())
        store.close()
        assert store.run_number == 8

    def test_unsafe_name_is_sanitized(self, tmp_path):
        store = RunStore.create(tmp_path, "a/b:c", schema=_schema())
        store.close()
        assert store.path.name == "a_b_c_0001.h5"


class TestSaveShot:
    def test_file_created(self, tmp_path):
        store = RunStore.create(tmp_path, "Exp", schema=_shot_schema())
        store.save_shot(0, _shot_frame())
        store.close()
        assert store.path.is_file()

    def test_scalars_round_trip(self, tmp_path):
        store = RunStore.create(tmp_path, "Exp", schema=_shot_schema())
        store.save_shot(0, _shot_frame())
        store.close()
        with tables.open_file(str(store.path)) as f:
            data = pd.DataFrame(f.root.data[:])
            assert data["result_mean_v"].iloc[0] == 1.5
            assert data["params_voltage"].iloc[0] == 3.3

    def test_multiple_shots_appended(self, tmp_path):
        store = RunStore.create(tmp_path, "Exp", schema=_shot_schema())
        store.save_shot(0, _shot_frame())
        store.save_shot(1, _shot_frame())
        store.save_shot(2, _shot_frame())
        store.close()
        with tables.open_file(str(store.path)) as f:
            data = pd.DataFrame(f.root.data[:])
            assert len(data) == 3
            assert list(data["shot_idx"]) == [0, 1, 2]

    def test_trace_stored_as_dataset(self, tmp_path):
        store = RunStore.create(tmp_path, "Exp", schema=_shot_schema(trace=True))
        trace = np.linspace(0.0, 1.0, 500, dtype=np.float32)
        store.save_shot(0, _shot_frame(trace=trace))
        store.close()

        with tables.open_file(str(store.path)) as f:
            data = pd.DataFrame(f.root.data[:])
            assert "result_trace" not in data.columns
            stored = f.root.traces.shot_00000.result_trace.read()
            # axis 0 is always the row axis, length 1 for a single-row shot
            assert stored.shape == (1, 500)
            assert np.allclose(stored[0], trace)

    def test_metadata_attrs(self, tmp_path):
        store = RunStore.create(tmp_path, "Exp", schema=_shot_schema())
        store.save_shot(0, _shot_frame())
        store.close()
        with tables.open_file(str(store.path)) as f:
            attrs = f.root._v_attrs
            assert attrs["experiment"] == "Exp"
            assert attrs["run_number"] == 1
            assert "T" in attrs["started_at"]

    def test_column_unit_and_description_written(self, tmp_path):
        schema = _schema(
            {"mean_v": _spec(float, unit="V", description="mean voltage")},
            {"voltage": param(3.3, unit="V")},
        )
        store = RunStore.create(tmp_path, "Exp", schema=schema)
        store.save_shot(0, _frame({"mean_v": [1.5]}, {"voltage": [3.3]}))
        store.close()
        with tables.open_file(str(store.path)) as f:
            attrs = f.root.data.attrs
            assert attrs["result_mean_v__unit"] == "V"
            assert attrs["result_mean_v__description"] == "mean voltage"
            assert attrs["params_voltage__unit"] == "V"

    def test_trace_unit_written_on_dataset(self, tmp_path):
        schema = _schema({"trace": _spec(np.ndarray, unit="V")}, {})
        store = RunStore.create(tmp_path, "Exp", schema=schema)
        store.save_shot(0, _frame({"trace": [np.zeros(10, dtype=np.float32)]}, {}))
        store.close()
        with tables.open_file(str(store.path)) as f:
            assert f.root.traces.shot_00000.result_trace._v_attrs["unit"] == "V"

    def test_no_traces_group_without_arrays(self, tmp_path):
        store = RunStore.create(tmp_path, "Exp", schema=_shot_schema())
        store.save_shot(0, _shot_frame())
        store.close()
        with tables.open_file(str(store.path)) as f:
            assert "traces" not in f.root

    def test_string_columns(self, tmp_path):
        schema = _schema({"value": _spec(float), "label": _spec(str)}, {})
        store = RunStore.create(tmp_path, "Exp", schema=schema)
        store.save_shot(0, _frame({"value": [1.5], "label": ["hello"]}, {}))
        store.close()
        with tables.open_file(str(store.path)) as f:
            data = pd.DataFrame(f.root.data[:])
            assert data["result_value"].iloc[0] == 1.5
            assert data["result_label"].iloc[0] == b"hello"

    def test_undeclared_column_rejected(self, tmp_path):
        store = RunStore.create(tmp_path, "Exp", schema=_schema({"a": _spec(float)}, {}))
        with pytest.raises(ValueError, match="not declared"):
            store.save_shot(0, _frame({"a": [1.0], "b": [2.0]}, {}))
        store.close()


class TestMultiRowShots:
    """A shot may return more than one row,  all rows share shot_idx."""

    @staticmethod
    def _batch_schema(*, trace: bool = False) -> RunSchema:
        results = {"rep": _spec(int), "mean_v": _spec(float)}
        if trace:
            results["trace"] = _spec(np.ndarray)
        return _schema(results, {"voltage": param(3.3)})

    @staticmethod
    def _batch_frame(n: int, *, trace_len: int | None = None) -> pd.DataFrame:
        result_cols = {"rep": list(range(n)), "mean_v": [0.1 * i for i in range(n)]}
        if trace_len is not None:
            result_cols["trace"] = [
                np.full(trace_len, float(i), dtype=np.float32) for i in range(n)
            ]
        return _frame(result_cols, {"voltage": [3.3] * n})

    def test_all_rows_appended_sharing_shot_idx(self, tmp_path):
        store = RunStore.create(tmp_path, "Exp", schema=self._batch_schema())
        store.save_shot(0, self._batch_frame(5))
        store.save_shot(1, self._batch_frame(5))
        store.close()
        with tables.open_file(str(store.path)) as f:
            data = pd.DataFrame(f.root.data[:])
            assert len(data) == 10
            assert list(data["shot_idx"]) == [0] * 5 + [1] * 5
            assert list(data["result_rep"]) == list(range(5)) * 2
            assert list(data["params_voltage"]) == [3.3] * 10

    def test_traces_stacked_per_column(self, tmp_path):
        store = RunStore.create(tmp_path, "Exp", schema=self._batch_schema(trace=True))
        store.save_shot(0, self._batch_frame(4, trace_len=100))
        store.close()
        with tables.open_file(str(store.path)) as f:
            stored = f.root.traces.shot_00000.result_trace.read()
            assert stored.shape == (4, 100)
            for i in range(4):
                assert np.all(stored[i] == np.float32(i))

    def test_trace_shape_is_consistent_across_row_counts(self, tmp_path):
        store = RunStore.create(tmp_path, "Exp", schema=self._batch_schema(trace=True))
        store.save_shot(0, self._batch_frame(1, trace_len=50))
        store.save_shot(1, self._batch_frame(4, trace_len=50))
        store.close()
        with tables.open_file(str(store.path)) as f:
            assert f.root.traces.shot_00000.result_trace.read().shape == (1, 50)
            assert f.root.traces.shot_00001.result_trace.read().shape == (4, 50)

    def test_unequal_trace_shapes_raise(self, tmp_path):
        schema = _schema({"trace": _spec(np.ndarray)}, {})
        frame = _frame(
            {"trace": [np.zeros(10, dtype=np.float32), np.zeros(20, dtype=np.float32)]}, {}
        )
        store = RunStore.create(tmp_path, "Exp", schema=schema)
        with pytest.raises(ValueError, match="equal-shape"):
            store.save_shot(0, frame)
        store.close()

    def test_empty_frame_writes_no_rows(self, tmp_path):
        # A view-only shot contributes an empty frame; the table is still created
        # from the declared schema so later shots append, but no rows are written.
        store = RunStore.create(tmp_path, "Exp", schema=_schema({"reading": _spec(float)}, {}))
        store.save_shot(0, _frame({"reading": []}, {}))
        store.save_shot(1, _frame({"reading": [1.5]}, {}))
        store.close()

        with tables.open_file(str(store.path)) as f:
            data = pd.DataFrame(f.root.data[:])
            assert list(data["shot_idx"]) == [1]
            assert list(data["result_reading"]) == [1.5]

    @pytest.mark.asyncio
    async def test_end_to_end_batched_shot(self, tmp_path):
        class BatchedTraceExperiment(Experiment):
            voltage = param(3.3, min=0.0, max=5.0, unit="V")

            class Record(Results):
                rep: int = result()
                mean_v: float = result()
                trace: np.ndarray = result()

            async def shot(self, ctx: Context) -> list[Record]:
                traces = [np.full(100, float(i), dtype=np.float32) for i in range(3)]
                return [
                    self.Record(rep=i, mean_v=float(t.mean()), trace=t)
                    for i, t in enumerate(traces)
                ]

        exp = BatchedTraceExperiment()
        exp.voltage = 2.0
        frame = await exp.record(Context(shot_idx=0))

        store = RunStore.create(
            tmp_path,
            "Batched",
            schema=RunSchema(
                results=BatchedTraceExperiment.results(),
                params=BatchedTraceExperiment.parameters(),
            ),
        )
        store.save_shot(0, frame)
        store.close()

        with tables.open_file(str(store.path)) as f:
            data = pd.DataFrame(f.root.data[:])
            assert len(data) == 3
            assert list(data["shot_idx"]) == [0, 0, 0]
            assert list(data["params_voltage"]) == [2.0, 2.0, 2.0]
            assert list(data["result_mean_v"]) == [0.0, 1.0, 2.0]
            assert f.root.traces.shot_00000.result_trace.read().shape == (3, 100)


class TestColumnMismatch:
    def test_extra_column_reported(self, tmp_path):
        schema = _schema({"a": _spec(float), "b": _spec(float), "c": _spec(float)}, {})
        store = RunStore.create(tmp_path, "Exp", schema=schema)
        store.save_shot(0, _frame({"a": [1.0], "b": [2.0]}, {}))
        with pytest.raises(ValueError, match=r"added \['result_c'\]"):
            store.save_shot(1, _frame({"a": [1.0], "b": [2.0], "c": [3.0]}, {}))
        store.close()

    def test_missing_column_reported(self, tmp_path):
        schema = _schema({"a": _spec(float), "b": _spec(float)}, {})
        store = RunStore.create(tmp_path, "Exp", schema=schema)
        store.save_shot(0, _frame({"a": [1.0], "b": [2.0]}, {}))
        with pytest.raises(ValueError, match=r"missing \['result_b'\]"):
            store.save_shot(1, _frame({"a": [1.0]}, {}))
        store.close()

    def test_both_directions_reported(self, tmp_path):
        schema = _schema({"a": _spec(float), "b": _spec(float), "c": _spec(float)}, {})
        store = RunStore.create(tmp_path, "Exp", schema=schema)
        store.save_shot(0, _frame({"a": [1.0], "b": [2.0]}, {}))
        with pytest.raises(ValueError, match=r"added.*missing|missing.*added"):
            store.save_shot(1, _frame({"a": [1.0], "c": [3.0]}, {}))
        store.close()


class TestTraces:
    def test_trace_dtype_preserved(self, tmp_path):
        store = RunStore.create(tmp_path, "Exp", schema=_shot_schema(trace=True))
        trace = np.linspace(0.0, 1.0, 100, dtype=np.float32)
        store.save_shot(0, _shot_frame(trace=trace))
        store.close()
        with tables.open_file(str(store.path)) as f:
            assert f.root.traces.shot_00000.result_trace.read().dtype == np.float32

    def test_multiple_trace_columns(self, tmp_path):
        samples = np.linspace(0.0, 1.0, 50)
        times = np.linspace(0.0, 5e-6, 50)
        schema = _schema(
            {"mean_v": _spec(float), "trace": _spec(np.ndarray), "times_s": _spec(np.ndarray)},
            {"voltage": param(3.3)},
        )
        frame = _frame(
            {"mean_v": [0.5], "trace": [samples], "times_s": [times]}, {"voltage": [3.3]}
        )
        store = RunStore.create(tmp_path, "Exp", schema=schema)
        store.save_shot(0, frame)
        store.close()
        with tables.open_file(str(store.path)) as f:
            assert np.allclose(f.root.traces.shot_00000.result_trace.read()[0], samples)
            assert np.allclose(f.root.traces.shot_00000.result_times_s.read()[0], times)
            data = pd.DataFrame(f.root.data[:])
            assert data["result_mean_v"].iloc[0] == 0.5
            assert data["params_voltage"].iloc[0] == 3.3

    def test_multichannel_2d_trace(self, tmp_path):
        """A 1-row shot with a (4, 250) multichannel trace stores as (1, 4, 250),
        so it cannot be confused with a 4-row shot of (250,) traces."""
        trace = np.random.default_rng(0).normal(size=(4, 250)).astype(np.float32)
        store = RunStore.create(tmp_path, "Exp", schema=_shot_schema(trace=True))
        store.save_shot(0, _shot_frame(trace=trace))
        store.close()
        with tables.open_file(str(store.path)) as f:
            stored = f.root.traces.shot_00000.result_trace.read()
            assert stored.shape == (1, 4, 250)
            assert np.array_equal(stored[0], trace)

    def test_large_trace_round_trip(self, tmp_path):
        trace = np.random.default_rng(1).normal(size=1_000_000).astype(np.float32)
        store = RunStore.create(tmp_path, "Exp", schema=_shot_schema(trace=True))
        store.save_shot(0, _shot_frame(trace=trace))
        store.close()
        with tables.open_file(str(store.path)) as f:
            stored = f.root.traces.shot_00000.result_trace.read()
            assert stored.shape == (1, 1_000_000)
            assert np.array_equal(stored[0], trace)

    def test_traces_per_shot(self, tmp_path):
        """Each shot's traces are stored under their own group."""
        store = RunStore.create(tmp_path, "Exp", schema=_shot_schema(trace=True))
        for i in range(3):
            trace = np.full(10, float(i), dtype=np.float32)
            store.save_shot(i, _shot_frame(trace=trace))
        store.close()
        with tables.open_file(str(store.path)) as f:
            for i in range(3):
                grp = f.root.traces._f_get_child(f"shot_{i:05d}")
                assert np.allclose(grp.result_trace.read()[0], float(i))

    @pytest.mark.asyncio
    async def test_end_to_end_experiment_shot_with_trace(self, tmp_path):
        """Full path: Experiment returns typed results, record() appends
        params, RunStore splits scalars from the trace dataset."""

        class TraceExperiment(Experiment):
            voltage = param(3.3, min=0.0, max=5.0, unit="V")

            class Record(Results):
                mean_v: float = result()
                trace: np.ndarray = result()

            async def shot(self, ctx: Context) -> list[Record]:
                samples = np.full(500, self.voltage, dtype=np.float32)
                return [self.Record(mean_v=float(samples.mean()), trace=samples)]

        exp = TraceExperiment()
        exp.voltage = 2.0
        frame = await exp.record(Context(shot_idx=0))

        store = RunStore.create(
            tmp_path,
            "Trace Experiment",
            schema=RunSchema(
                results=TraceExperiment.results(), params=TraceExperiment.parameters()
            ),
        )
        store.save_shot(0, frame)
        store.close()

        with tables.open_file(str(store.path)) as f:
            data = pd.DataFrame(f.root.data[:])
            assert data["params_voltage"].iloc[0] == 2.0
            assert data["result_mean_v"].iloc[0] == 2.0
            assert "result_trace" not in data.columns
            stored = f.root.traces.shot_00000.result_trace.read()
            assert stored.shape == (1, 500)
            assert np.all(stored == np.float32(2.0))


class TestSchemaPickling:
    """The schema travels to the writer process, so it has to survive a pickle."""

    class Probe(Experiment):
        voltage = param(3.3, min=0.0, max=5.0, unit="V")

        class Record(Results):
            mean_v: float = result(unit="V")
            trace: np.ndarray = result(description="raw samples")

        async def shot(self, ctx: Context) -> list[Record]:
            return [self.Record(mean_v=0.0, trace=np.zeros(4))]

    def test_round_trips_specs_from_a_live_experiment(self):
        # parameters()/results() hand out mappingproxies, which do not pickle;
        # build the schema exactly as the engine does so that shows up here.
        schema = RunSchema(
            results=self.Probe.results(),
            params=self.Probe.parameters(),
            metadata={"n_samples": "4"},
        )

        restored = pickle.loads(pickle.dumps(schema))

        assert restored.columns() == schema.columns()
        assert dict(restored.metadata) == {"n_samples": "4"}
        assert restored.results["trace"].dtype is np.ndarray
        assert restored.params["voltage"].unit == "V"
