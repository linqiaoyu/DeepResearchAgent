# Local Qdrant capacity and quantization measurement

This measurement is local-only and uses deterministic fixture vectors; it does
not invoke embedding/rerank providers or change the online collection.

On local Colima Qdrant v1.18.3, 20,000 1024-dimensional on-disk vectors used
279,601,674 bytes (13,980.08 bytes/point). The linear 100,000-point capacity
extrapolation is therefore **推测**: 1,398,008,370 bytes. It is a sizing aid,
not a quality or production gate.

For the dimensional/quantization comparison, a separate 20,000-point 256-D
collection configured with scalar int8 quantization used 164,355,721 bytes
(8,217.79 bytes/point), versus the 1024-D baseline. The source is
`artifacts/047/qdrant_local_capacity_probe.log` and the container `du` output
in `artifacts/047/qdrant_local_capacity_disk.log`. The collections are local,
disposable, and named `dr047_*`; no online configuration was changed.
