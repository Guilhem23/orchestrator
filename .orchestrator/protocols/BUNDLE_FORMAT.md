# Method v4 Policy-Bundle Digest Format

Identifier: `sorted_relative_path_nul_length_bytes_v1`

The bundle digest is SHA-256 over:

1. ASCII prefix `slice-orchestrator-v4/policy-bundle/v1` followed by one NUL
   byte;
2. one entry for each path in `slice-policy.yaml` `required_files`, sorted by
   normalized path UTF-8 bytes;
3. each entry encoded as:
   - unsigned 64-bit big-endian path-byte length;
   - normalized relative path UTF-8 bytes;
   - unsigned 64-bit big-endian content-byte length;
   - exact file content bytes.

Path rules:

- paths must satisfy `PATH_SEMANTICS.md`;
- each required path appears exactly once;
- directories, symlinks, hard-link identity, metadata, timestamps, ownership,
  and mode bits are not entries;
- every required path must be a regular file;
- undeclared files do not affect the digest and are not installed;
- the expected digest is stored outside the implementation workspace.

Known-answer vector:

```text
a.txt  = bytes 41 0a
dir/b  = empty
```

Expected digest:

`81ffd432606538ff752acc9dc95f49866c869bf2681334fd2f476bf47783000b`

The runtime acceptance suite must verify this vector and cross-process
determinism.
