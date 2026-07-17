import numpy as np
import pandas as pd
import pytest
import tables

from h2pcontrol.controller.framework.experiment import Context, Experiment
from h2pcontrol.controller.framework.parameters import param
from h2pcontrol.controller.runtime.store import RunStore


def _shot_frame(*, trace=None) -> pd.DataFrame:
    result = {"mean_v": [1.5], "n_samples": [1000]}
    if trace is not None:
        result["trace"] = [trace]
    frame = pd.concat(
        [
            pd.DataFrame(result),
            pd.DataFrame({"voltage": [3.3]}),
        ],
        axis=1,
        keys=["result", "params"],
    )
    return frame


class TestRunNumbering:
    def test_first_run_is_one(self, tmp_path):
        store = RunStore.create(tmp_path, "My Experiment")
        store.close()
        assert store.run_number == 1
        assert store.path == tmp_path / "My Experiment_0001.h5"
        assert store.path.is_file()

    def test_run_number_auto_increments(self, tmp_path):
        RunStore.create(tmp_path, "Exp").close()
        RunStore.create(tmp_path, "Exp").close()
        store = RunStore.create(tmp_path, "Exp")
        store.close()
        assert store.run_number == 3
        assert store.path.name == "Exp_0003.h5"

    def test_runs_are_per_experiment(self, tmp_path):
        RunStore.create(tmp_path, "A").close()
        store = RunStore.create(tmp_path, "B")
        store.close()
        assert store.run_number == 1

    def test_gaps_do_not_collide(self, tmp_path):
        RunStore.create(tmp_path, "Exp").close()
        tables.open_file(str(tmp_path / "Exp_0007.h5"), mode="w").close()
        store = RunStore.create(tmp_path, "Exp")
        store.close()
        assert store.run_number == 8

    def test_unsafe_name_is_sanitized(self, tmp_path):
        store = RunStore.create(tmp_path, "a/b:c")
        store.close()
        assert store.path.name == "a_b_c_0001.h5"


class TestSaveShot:
    def test_file_created(self, tmp_path):
        store = RunStore.create(tmp_path, "Exp")
        store.save_shot(0, _shot_frame())
        store.close()
        assert store.path.is_file()

    def test_scalars_round_trip(self, tmp_path):
        store = RunStore.create(tmp_path, "Exp")
        store.save_shot(0, _shot_frame())
        store.close()
        with tables.open_file(str(store.path)) as f:
            data = pd.DataFrame(f.root.data[:])
            assert data["result_mean_v"].iloc[0] == 1.5
            assert data["params_voltage"].iloc[0] == 3.3

    def test_multiple_shots_appended(self, tmp_path):
        store = RunStore.create(tmp_path, "Exp")
        store.save_shot(0, _shot_frame())
        store.save_shot(1, _shot_frame())
        store.save_shot(2, _shot_frame())
        store.close()
        with tables.open_file(str(store.path)) as f:
            data = pd.DataFrame(f.root.data[:])
            assert len(data) == 3
            assert list(data["shot_idx"]) == [0, 1, 2]

    def test_trace_stored_as_dataset(self, tmp_path):
        store = RunStore.create(tmp_path, "Exp")
        trace = np.linspace(0.0, 1.0, 500, dtype=np.float32)
        store.save_shot(0, _shot_frame(trace=trace))
        store.close()

        with tables.open_file(str(store.path)) as f:
            data = pd.DataFrame(f.root.data[:])
            assert "result_trace" not in data.columns
            stored = f.root.traces.shot_00000.result_trace.read()
            assert stored.shape == (500,)
            assert np.allclose(stored, trace)

    def test_metadata_attrs(self, tmp_path):
        store = RunStore.create(tmp_path, "Exp")
        store.save_shot(0, _shot_frame())
        store.close()
        with tables.open_file(str(store.path)) as f:
            attrs = f.root._v_attrs
            assert attrs["experiment"] == "Exp"
            assert attrs["run_number"] == 1
            assert "T" in attrs["started_at"]

    def test_no_traces_group_without_arrays(self, tmp_path):
        store = RunStore.create(tmp_path, "Exp")
        store.save_shot(0, _shot_frame())
        store.close()
        with tables.open_file(str(store.path)) as f:
            assert "traces" not in f.root

    def test_plain_columns_without_multiindex(self, tmp_path):
        store = RunStore.create(tmp_path, "Exp")
        store.save_shot(0, pd.DataFrame({"reading": [1.0]}))
        store.close()
        with tables.open_file(str(store.path)) as f:
            data = pd.DataFrame(f.root.data[:])
            assert data["reading"].iloc[0] == 1.0

    def test_string_columns(self, tmp_path):
        store = RunStore.create(tmp_path, "Exp")
        frame = pd.DataFrame({"value": [1.5], "label": ["hello"]})
        store.save_shot(0, frame)
        store.close()
        with tables.open_file(str(store.path)) as f:
            data = pd.DataFrame(f.root.data[:])
            assert data["value"].iloc[0] == 1.5
            assert data["label"].iloc[0] == b"hello"


class TestTraces:
    def test_trace_dtype_preserved(self, tmp_path):
        store = RunStore.create(tmp_path, "Exp")
        trace = np.linspace(0.0, 1.0, 100, dtype=np.float32)
        store.save_shot(0, _shot_frame(trace=trace))
        store.close()
        with tables.open_file(str(store.path)) as f:
            assert f.root.traces.shot_00000.result_trace.read().dtype == np.float32

    def test_multiple_trace_columns(self, tmp_path):
        samples = np.linspace(0.0, 1.0, 50)
        times = np.linspace(0.0, 5e-6, 50)
        frame = pd.concat(
            [
                pd.DataFrame({"mean_v": [0.5], "trace": [samples], "times_s": [times]}),
                pd.DataFrame({"voltage": [3.3]}),
            ],
            axis=1,
            keys=["result", "params"],
        )
        store = RunStore.create(tmp_path, "Exp")
        store.save_shot(0, frame)
        store.close()
        with tables.open_file(str(store.path)) as f:
            assert np.allclose(f.root.traces.shot_00000.result_trace.read(), samples)
            assert np.allclose(f.root.traces.shot_00000.result_times_s.read(), times)
            data = pd.DataFrame(f.root.data[:])
            assert data["result_mean_v"].iloc[0] == 0.5
            assert data["params_voltage"].iloc[0] == 3.3

    def test_multichannel_2d_trace(self, tmp_path):
        trace = np.random.default_rng(0).normal(size=(4, 250)).astype(np.float32)
        store = RunStore.create(tmp_path, "Exp")
        store.save_shot(0, _shot_frame(trace=trace))
        store.close()
        with tables.open_file(str(store.path)) as f:
            stored = f.root.traces.shot_00000.result_trace.read()
            assert stored.shape == (4, 250)
            assert np.array_equal(stored, trace)

    def test_large_trace_round_trip(self, tmp_path):
        trace = np.random.default_rng(1).normal(size=1_000_000).astype(np.float32)
        store = RunStore.create(tmp_path, "Exp")
        store.save_shot(0, _shot_frame(trace=trace))
        store.close()
        with tables.open_file(str(store.path)) as f:
            stored = f.root.traces.shot_00000.result_trace.read()
            assert np.array_equal(stored, trace)

    def test_traces_per_shot(self, tmp_path):
        """Each shot's traces are stored under their own group."""
        store = RunStore.create(tmp_path, "Exp")
        for i in range(3):
            trace = np.full(10, float(i), dtype=np.float32)
            store.save_shot(i, _shot_frame(trace=trace))
        store.close()
        with tables.open_file(str(store.path)) as f:
            for i in range(3):
                grp = f.root.traces._f_get_child(f"shot_{i:05d}")
                assert np.allclose(grp.result_trace.read(), float(i))

    @pytest.mark.asyncio
    async def test_end_to_end_experiment_shot_with_trace(self, tmp_path):
        """Full path: Experiment returns a trace column, _wrap_shot appends
        params, RunStore splits scalars from the trace dataset."""

        class TraceExperiment(Experiment):
            voltage = param(3.3, min=0.0, max=5.0, unit="V")

            async def shot(self, ctx: Context) -> pd.DataFrame:
                samples = np.full(500, self.voltage, dtype=np.float32)
                return pd.DataFrame({"mean_v": [float(samples.mean())], "trace": [samples]})

        exp = TraceExperiment()
        exp.voltage = 2.0
        frame = await exp.shot(Context(shot_idx=0))

        store = RunStore.create(tmp_path, "Trace Experiment")
        store.save_shot(0, frame)
        store.close()

        with tables.open_file(str(store.path)) as f:
            data = pd.DataFrame(f.root.data[:])
            assert data["params_voltage"].iloc[0] == 2.0
            assert data["result_mean_v"].iloc[0] == 2.0
            assert "result_trace" not in data.columns
            stored = f.root.traces.shot_00000.result_trace.read()
            assert stored.shape == (500,)
            assert np.all(stored == np.float32(2.0))
