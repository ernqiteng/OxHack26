"""scripts/gpu_box.py against a fake Vultr client: it can only ever touch the tagged GPU box, the create
body is exactly the approved one, and delete never reaches the backend or the workers. No network."""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "gpu_box.py"
spec = importlib.util.spec_from_file_location("gpu_box", SCRIPT)
gb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gb)

BACKEND = {
    "id": "b1",
    "label": "tempo-backend",
    "tags": ["tempo", "tempo-backend"],
    "main_ip": "136.244.77.120",
}
WORKERS = [
    {"id": f"w{i}", "label": f"tempo-worker-{i}", "tags": ["tempo", "tempo-worker"]} for i in range(1, 6)
]
IMPOSTOR = {
    "id": "x1",
    "label": "tempo-backend",
    "tags": ["tempo-gpu"],
}  # right tag, wrong label: never touch


class FakeVultr:
    def __init__(self, instances, keys=({"id": "k-gpu", "name": "tempo-girik-gpu"},)):
        self.instances = [dict(i) for i in instances]
        self.keys = [dict(k) for k in keys]
        self.created, self.deleted, self.added_keys = [], [], []

    def list_instances(self, tag=None):
        # The server-side tag filter is trusted only partly: return everything carrying the tag.
        return [i for i in self.instances if tag is None or tag in (i.get("tags") or [])]

    def list_ssh_keys(self):
        return self.keys

    def create_ssh_key(self, name, pub):
        self.added_keys.append((name, pub))
        key = {"id": "k-new", "name": name}
        self.keys.append(key)
        return key

    def create_instance(self, label, **body):
        self.created.append({"label": label, **body})
        inst = {"id": "g1", "label": label, "tags": body["tags"], "main_ip": "1.2.3.4",
                "date_created": "2026-10-25T10:00:00+00:00", "status": "active"}  # fmt: skip
        self.instances.append(inst)
        return type("W", (), {"instance_id": "g1", "main_ip": "1.2.3.4"})()

    def delete_instance(self, instance_id):
        self.deleted.append(instance_id)
        self.instances = [i for i in self.instances if i["id"] != instance_id]


def test_only_the_tagged_and_labelled_box_is_ever_seen():
    gpu = {"id": "g1", "label": "tempo-gpu-1", "tags": ["tempo", "tempo-gpu"]}
    client = FakeVultr([BACKEND, *WORKERS, IMPOSTOR, gpu])
    assert [b["id"] for b in gb.gpu_boxes(client)] == ["g1"]


def test_create_sends_exactly_the_approved_body():
    client = FakeVultr([BACKEND, *WORKERS])
    gb.create(client, wait=False)
    assert client.created == [
        {"label": "tempo-gpu-1", "region": "lhr", "plan": "vcg-a16-6c-60g-16vram", "os_id": 1743,
         "sshkey_ids": ["k-gpu"], "tags": ["tempo", "tempo-gpu"], "hostname": "tempo-gpu-1"}
    ]  # fmt: skip


def test_create_refuses_a_second_box():
    client = FakeVultr([BACKEND, {"id": "g1", "label": "tempo-gpu-1", "tags": ["tempo-gpu"]}])
    with pytest.raises(SystemExit, match="already exists"):
        gb.create(client, wait=False)
    assert client.created == []


def test_create_needs_our_key():
    client = FakeVultr([BACKEND], keys=({"id": "k-ayo", "name": "tempo-Ayomide"},))
    with pytest.raises(SystemExit, match="add-key"):
        gb.create(client, wait=False)
    assert client.created == []


def test_delete_removes_only_the_gpu_box():
    gpu = {"id": "g1", "label": "tempo-gpu-1", "tags": ["tempo", "tempo-gpu"]}
    client = FakeVultr([BACKEND, *WORKERS, IMPOSTOR, gpu])
    gb.delete(client, sleep=lambda s: None)
    assert client.deleted == ["g1"]
    assert {i["id"] for i in client.instances} == {"b1", "w1", "w2", "w3", "w4", "w5", "x1"}


def test_delete_with_no_box_touches_nothing():
    client = FakeVultr([BACKEND, *WORKERS, IMPOSTOR])
    gb.delete(client, sleep=lambda s: None)
    assert client.deleted == []


def test_add_key_is_idempotent(tmp_path):
    pub = tmp_path / "k.pub"
    pub.write_text("ssh-ed25519 AAAA tempo-girik-gpu\n")
    client = FakeVultr([], keys=())
    assert gb.add_key(client, pub) == "k-new"
    assert gb.add_key(client, pub) == "k-new"
    assert len(client.added_keys) == 1


def test_status_reports_cost(capsys):
    client = FakeVultr([{"id": "g1", "label": "tempo-gpu-1", "tags": ["tempo-gpu"], "main_ip": "1.2.3.4",
                         "status": "active", "date_created": "2026-10-25T10:00:00+00:00"}])  # fmt: skip
    gb.status(client, now=datetime(2026, 10, 25, 12, 0, tzinfo=UTC))
    assert "up 2.00 h, about $0.94 so far" in capsys.readouterr().out


@pytest.mark.parametrize(
    "smi,expected",
    [("| NVIDIA-SMI 550.54  Driver Version: 550.54  CUDA Version: 12.4 |", "cu124"),
     ("CUDA Version: 12.2", "cu121"), ("CUDA Version: 11.8", "cu118")],
)  # fmt: skip
def test_cuda_wheel_matches_the_driver(smi, expected):
    assert gb.cuda_wheel_index(smi).endswith(expected)


def test_no_cuda_version_is_an_error():
    with pytest.raises(ValueError):
        gb.cuda_wheel_index("NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver")
