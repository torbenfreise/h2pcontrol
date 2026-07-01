import pytest

from h2pcontrol.controller.framework.scan import Axis, Scan


class TestAxis:
    def test_values_linearly_spaced(self):
        ax = Axis(param="voltage", start=0.0, stop=1.0, steps=3)
        vals = list(ax.values)
        assert vals == pytest.approx([0.0, 0.5, 1.0])


class TestScan:
    def test_requires_at_least_one_axis(self):
        with pytest.raises(ValueError):
            Scan()

    def test_single_axis_len(self):
        scan = Scan(Axis(param="v", start=0, stop=1, steps=5))
        assert len(scan) == 5

    def test_multi_axis_len(self):
        scan = Scan(
            Axis(param="v", start=0, stop=1, steps=3),
            Axis(param="f", start=1, stop=10, steps=4),
        )
        assert len(scan) == 12

    def test_single_axis_points(self):
        scan = Scan(Axis(param="voltage", start=0.0, stop=1.0, steps=3))
        points = list(scan.points())
        assert len(points) == 3
        assert points[0] == {"voltage": pytest.approx(0.0)}
        assert points[1] == {"voltage": pytest.approx(0.5)}
        assert points[2] == {"voltage": pytest.approx(1.0)}

    def test_multi_axis_cartesian_product(self):
        scan = Scan(
            Axis(param="x", start=0, stop=1, steps=2),
            Axis(param="y", start=10, stop=20, steps=2),
        )
        points = list(scan.points())
        assert len(points) == 4
        assert points[0] == {"x": pytest.approx(0.0), "y": pytest.approx(10.0)}
        assert points[1] == {"x": pytest.approx(0.0), "y": pytest.approx(20.0)}
        assert points[2] == {"x": pytest.approx(1.0), "y": pytest.approx(10.0)}
        assert points[3] == {"x": pytest.approx(1.0), "y": pytest.approx(20.0)}
