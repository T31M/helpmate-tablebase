#include "format/table_file.h"

#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

#include <algorithm>
#include <array>
#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <memory>
#include <stdexcept>
#include <system_error>
#include <vector>

#include "format/block_codec.h"

namespace hm {

constexpr uint8_t kFlagAllUnsolvable = 0x01;

namespace {
// The block index sits at a byte offset that depends on `json_len`, an
// arbitrary value read from the file, so index entries are not generally
// aligned to uint64_t's 8-byte requirement. A `reinterpret_cast<const
// uint64_t*>` followed by a direct dereference is undefined behavior on a
// misaligned pointer -- UBSan reports it against the committed golden
// fixture. Read through memcpy instead, exactly like the block count itself
// (`stated`, just above every call site below) already does.
inline uint64_t load_u64(const uint8_t* p) {
    uint64_t v;
    std::memcpy(&v, p, sizeof(v));
    return v;
}
}  // namespace

namespace {
// compress_existing streams sequentially through a read-only mmap of the
// source table and never revisits a byte. Left alone, the pages it has
// already read stay resident (clean page-cache pages have no reason to be
// reclaimed until something else needs the memory), so on a box with plenty
// of free RAM -- exactly where this would go unnoticed -- the OS-reported
// RSS climbs to the whole file's size even though no buffer proportional to
// plane_size was ever allocated. MADV_DONTNEED tells the kernel those pages
// really are done with: they drop from this process's resident set now,
// unconditionally, not only under memory pressure. That is what keeps a
// six-piece conversion's actual footprint bounded rather than merely
// hoping the machine happens to be tight on memory when it runs.
class SequentialPageReleaser {
public:
    SequentialPageReleaser(const uint8_t* base, uint64_t total) : base_(base), total_(total) {
        // madvise() requires a page-aligned address. `base` is the payload
        // pointer -- an arbitrary byte offset into the mapping, right after
        // the header and JSON, not the mapping's own page-aligned start -- so
        // aligning `released_` (a byte count from `base`) to a multiple of
        // the page size would still leave `base + released_` misaligned in
        // absolute terms whenever that header+JSON prefix isn't itself a
        // multiple of the page size. Round the first release point up to the
        // next page boundary in ABSOLUTE address terms instead; every
        // `advance()` after that stays on an absolute page boundary too,
        // since it only ever adds page-sized increments.
        const uintptr_t page = static_cast<uintptr_t>(sysconf(_SC_PAGESIZE));
        const uintptr_t addr = reinterpret_cast<uintptr_t>(base_);
        const uintptr_t aligned_addr = ((addr + page - 1) / page) * page;
        released_ = aligned_addr - addr;

        // MADV_SEQUENTIAL is a hint too, and must be given the same
        // page-aligned address/length the kernel requires for any madvise()
        // call -- `base_` itself is not page-aligned (see above), so advise
        // starting at the same aligned address, covering what remains from
        // there. Both this call and MADV_DONTNEED below are best-effort
        // performance hints, not correctness requirements: a failure (e.g.
        // EINVAL from a still-misaligned length) only means the kernel
        // readahead/reclaim behavior degrades to its default, never a
        // conversion failure. The return is deliberately not fatal, but it
        // IS logged -- so a future regression here (like the one this fix
        // corrects) is visible in stderr instead of silently costing
        // performance forever.
        if (released_ < total_) {
            if (madvise(const_cast<uint8_t*>(base_) + released_, static_cast<size_t>(total_ - released_),
                        MADV_SEQUENTIAL) != 0) {
                std::fprintf(stderr, "warning: madvise(MADV_SEQUENTIAL) failed: %s\n", std::strerror(errno));
            }
        }
    }
    // Releases whole pages fully before `consumed_end` (exclusive), in chunks
    // -- not one madvise() per block -- so the syscall overhead stays
    // negligible against zstd's per-block work.
    void advance(uint64_t consumed_end) {
        static constexpr uint64_t kChunk = 8 * 1024 * 1024;  // release in 8 MiB steps
        const uintptr_t page = static_cast<uintptr_t>(sysconf(_SC_PAGESIZE));
        const uintptr_t base_addr = reinterpret_cast<uintptr_t>(base_);
        const uintptr_t consumed_addr = base_addr + consumed_end;
        const uintptr_t aligned_end_addr = (consumed_addr / page) * page;  // floor: never a partial page
        if (aligned_end_addr <= base_addr + released_) return;
        const uint64_t aligned_end = aligned_end_addr - base_addr;
        if (aligned_end - released_ < kChunk) return;
        // Best-effort, same as MADV_SEQUENTIAL above: on failure the pages
        // simply stay resident longer (worse RSS, not incorrect results), so
        // this does not throw -- but it does log, so a regression here is
        // visible rather than silently degrading a six-piece conversion's
        // memory footprint.
        if (madvise(const_cast<uint8_t*>(base_) + released_, static_cast<size_t>(aligned_end - released_),
                    MADV_DONTNEED) != 0) {
            std::fprintf(stderr, "warning: madvise(MADV_DONTNEED) failed: %s\n", std::strerror(errno));
        }
        released_ = aligned_end;
    }

private:
    const uint8_t* base_;
    uint64_t total_;
    uint64_t released_ = 0;
};
}  // namespace

namespace {
// Shared by write_compressed and compress_existing: writes the header, JSON,
// block index and compressed payload to "<path>.tmp", then atomic-renames it
// over `path`. `block_at(begin, len)` must return a pointer to `len` valid
// bytes for the block starting at logical offset `begin`, valid until the
// call returns.
//
// write_compressed's four planes are separate buffers, so its block_at
// gathers each block into a small reusable scratch buffer (block_size
// bytes) -- unchanged from before this refactor. compress_existing's source
// table is a raw file's mmap, where the four planes already sit contiguous
// in the mapping; its block_at hands back a pointer straight into that
// mapping, so no plane is ever buffered and memory stays O(block_size), not
// O(plane_size).
template <class BlockAt>
void write_block_compressed(const std::string& path, const TableHeader& hdr, const std::string& meta_json,
                            uint64_t logical_size, uint32_t block_size, int level, BlockAt block_at) {
    if (block_size == 0) throw std::runtime_error("write_block_compressed: block_size is zero");
    const uint64_t nblocks = block_count(logical_size, block_size);

    std::string tmp_path = path + ".tmp";
    try {
        std::ofstream out(tmp_path, std::ios::binary | std::ios::trunc);
        if (!out) throw std::runtime_error("write_block_compressed: cannot open " + tmp_path);
        out.write(reinterpret_cast<const char*>(&hdr), sizeof(hdr));
        out.write(meta_json.data(), static_cast<std::streamsize>(meta_json.size()));

        // Reserve the index, then rewrite it once the offsets are known: a
        // one-pass writer would have to buffer the whole compressed payload.
        const std::streampos index_pos = out.tellp();
        std::vector<uint64_t> offsets(nblocks + 1, 0);
        out.write(reinterpret_cast<const char*>(&nblocks), sizeof(nblocks));
        out.write(reinterpret_cast<const char*>(offsets.data()),
                  static_cast<std::streamsize>(offsets.size() * sizeof(uint64_t)));

        uint64_t written = 0;
        for (uint64_t b = 0; b < nblocks; ++b) {
            const uint64_t begin = b * block_size;
            const size_t len = static_cast<size_t>(std::min<uint64_t>(block_size, logical_size - begin));
            const uint8_t* src = block_at(begin, len);
            auto packed = compress_block(src, len, level);
            offsets[b] = written;
            out.write(reinterpret_cast<const char*>(packed.data()),
                      static_cast<std::streamsize>(packed.size()));
            written += packed.size();
        }
        offsets[nblocks] = written;

        out.seekp(index_pos + static_cast<std::streamoff>(sizeof(uint64_t)));
        out.write(reinterpret_cast<const char*>(offsets.data()),
                  static_cast<std::streamsize>(offsets.size() * sizeof(uint64_t)));
        if (!out) throw std::runtime_error("write_block_compressed: write failed for " + tmp_path);

        // Close explicitly and check the result: the final index rewrite
        // above is exactly the write most likely to still be buffered when
        // the destructor's implicit close runs, and an implicit close does
        // not report failure to anyone. For compress_existing, `path` is the
        // user's only copy of a table -- flushing this without checking, then
        // renaming over that copy regardless, would silently replace it with
        // a truncated index that still passes open()'s structural checks
        // (an all-zero offsets array is monotone and offs[0]==0) and only
        // fails on the first probe.
        out.close();
        if (!out) throw std::runtime_error("write_block_compressed: close failed for " + tmp_path);

        // Cheap end-to-end integrity check before the atomic rename
        // overwrites the source: open() already validates the whole block
        // index (stated count, monotone in-bounds offsets), so reopening the
        // freshly written file here catches a corrupt flush that the OS
        // reported success for -- a near-free guard on data that may be
        // irreplaceable (89.7 GB in the six-piece case).
        {
            TableReader::OpenError verify_err = TableReader::OpenError::None;
            auto verify = TableReader::open(tmp_path, &verify_err);
            if (!verify)
                throw std::runtime_error("write_block_compressed: " + tmp_path +
                                         " failed to reopen for verification after writing");
        }
    } catch (...) {
        std::error_code ec;
        std::filesystem::remove(tmp_path, ec);  // best-effort cleanup; ignore removal errors
        throw;
    }
    std::filesystem::rename(tmp_path, path);
}
}  // namespace

void TableWriter::write(const std::string& path, const Material& mat, uint64_t plane_size, uint8_t max_dtm,
                        const std::string& meta_json, const uint8_t* dtm_w, const uint8_t* dtm_b,
                        const uint8_t* cnt_w, const uint8_t* cnt_b) {
    TableHeader hdr{};
    std::memcpy(hdr.magic, "HM8P", 4);
    hdr.version = 1;
    hdr.encoding = 1;
    hdr.symmetry = mat.has_pawns() ? 0 : 1;
    std::memset(hdr.material, 0, sizeof(hdr.material));
    std::string name = mat.name();
    std::memcpy(hdr.material, name.data(), std::min(name.size(), sizeof(hdr.material)));
    hdr.plane_size = plane_size;
    hdr.max_dtm = max_dtm;
    std::memset(hdr.reserved, 0, sizeof(hdr.reserved));
    hdr.json_len = static_cast<uint32_t>(meta_json.size());

    std::string tmp_path = path + ".tmp";
    try {
        std::ofstream out(tmp_path, std::ios::binary | std::ios::trunc);
        if (!out) throw std::runtime_error("TableWriter::write: cannot open " + tmp_path);
        out.write(reinterpret_cast<const char*>(&hdr), sizeof(hdr));
        out.write(meta_json.data(), static_cast<std::streamsize>(meta_json.size()));
        out.write(reinterpret_cast<const char*>(dtm_w), static_cast<std::streamsize>(plane_size));
        out.write(reinterpret_cast<const char*>(dtm_b), static_cast<std::streamsize>(plane_size));
        out.write(reinterpret_cast<const char*>(cnt_w), static_cast<std::streamsize>(plane_size));
        out.write(reinterpret_cast<const char*>(cnt_b), static_cast<std::streamsize>(plane_size));
        if (!out) throw std::runtime_error("TableWriter::write: write failed for " + tmp_path);
    } catch (...) {
        std::error_code ec;
        std::filesystem::remove(tmp_path, ec);  // best-effort cleanup; ignore removal errors
        throw;
    }
    std::filesystem::rename(tmp_path, path);
}

void TableWriter::write_unsolvable(const std::string& path, const Material& mat, uint64_t plane_size,
                                   const std::string& meta_json) {
    TableHeader hdr{};
    std::memcpy(hdr.magic, "HM8P", 4);
    hdr.version = 2;  // marker tables only
    hdr.encoding = 1;
    hdr.symmetry = mat.has_pawns() ? 0 : 1;
    std::memset(hdr.material, 0, sizeof(hdr.material));
    std::string name = mat.name();
    std::memcpy(hdr.material, name.data(), std::min(name.size(), sizeof(hdr.material)));
    hdr.plane_size = plane_size;
    hdr.max_dtm = DTM_UNSOLVABLE;
    hdr.flags = kFlagAllUnsolvable;
    std::memset(hdr.reserved, 0, sizeof(hdr.reserved));
    hdr.json_len = static_cast<uint32_t>(meta_json.size());

    std::string tmp_path = path + ".tmp";
    try {
        std::ofstream out(tmp_path, std::ios::binary | std::ios::trunc);
        if (!out) throw std::runtime_error("TableWriter::write_unsolvable: cannot open " + tmp_path);
        out.write(reinterpret_cast<const char*>(&hdr), sizeof(hdr));
        out.write(meta_json.data(), static_cast<std::streamsize>(meta_json.size()));
        if (!out) throw std::runtime_error("TableWriter::write_unsolvable: write failed for " + tmp_path);
    } catch (...) {
        std::error_code ec;
        std::filesystem::remove(tmp_path, ec);  // best-effort cleanup; ignore removal errors
        throw;
    }
    std::filesystem::rename(tmp_path, path);
}

void TableWriter::write_compressed(const std::string& path, const Material& mat, uint64_t plane_size,
                                   uint8_t max_dtm, const std::string& meta_json, const uint8_t* dtm_w,
                                   const uint8_t* dtm_b, const uint8_t* cnt_w, const uint8_t* cnt_b,
                                   uint32_t block_size, int level) {
    if (block_size == 0) throw std::runtime_error("write_compressed: block_size is zero");
    TableHeader hdr{};
    std::memcpy(hdr.magic, "HM8P", 4);
    // Version 3 as well as encoding 2: the reader validates `encoding`, but only
    // `version` drives the "written by a newer helpmate" diagnostic, so a binary
    // released before this format says the useful thing instead of "unreadable".
    hdr.version = 3;
    hdr.encoding = kEncodingBlocks;
    hdr.symmetry = mat.has_pawns() ? 0 : 1;
    std::memset(hdr.material, 0, sizeof(hdr.material));
    std::string name = mat.name();
    std::memcpy(hdr.material, name.data(), std::min(name.size(), sizeof(hdr.material)));
    hdr.plane_size = plane_size;
    hdr.max_dtm = max_dtm;
    hdr.block_size = block_size;
    hdr.codec = kCodecZstd;
    std::memset(hdr.reserved, 0, sizeof(hdr.reserved));
    hdr.json_len = static_cast<uint32_t>(meta_json.size());

    // The four planes are one logical byte range, in the same order the raw
    // layout uses: dtm_w, dtm_b, cnt_w, cnt_b. They are four separate
    // buffers, so each block is gathered into a small reusable scratch
    // buffer -- unlike compress_existing below, whose source planes are
    // already contiguous in its mmap and need no gathering at all.
    const uint8_t* planes[4] = {dtm_w, dtm_b, cnt_w, cnt_b};
    const uint64_t logical = 4 * plane_size;
    std::vector<uint8_t> scratch(block_size);
    write_block_compressed(path, hdr, meta_json, logical, block_size, level,
                           [&](uint64_t begin, size_t len) -> const uint8_t* {
                               for (size_t i = 0; i < len; ++i) {
                                   const uint64_t o = begin + i;
                                   scratch[i] = planes[o / plane_size][o % plane_size];
                               }
                               return scratch.data();
                           });
}

void TableWriter::compress_existing(const std::string& path, const TableReader& src, uint32_t block_size,
                                    int level) {
    if (src.all_unsolvable())
        throw std::runtime_error(
            "compress_existing: source table is a marker with no payload to stream at all");
    auto mat = Material::parse(src.material_name());
    if (!mat)
        throw std::runtime_error("compress_existing: unparseable material in source table: " +
                                 src.material_name());

    TableHeader hdr{};
    std::memcpy(hdr.magic, "HM8P", 4);
    hdr.version = 3;
    hdr.encoding = kEncodingBlocks;
    hdr.symmetry = mat->has_pawns() ? 0 : 1;
    std::memset(hdr.material, 0, sizeof(hdr.material));
    std::string name = mat->name();
    std::memcpy(hdr.material, name.data(), std::min(name.size(), sizeof(hdr.material)));
    hdr.plane_size = src.plane_size();
    hdr.max_dtm = src.max_dtm();
    hdr.block_size = block_size;
    hdr.codec = kCodecZstd;
    std::memset(hdr.reserved, 0, sizeof(hdr.reserved));
    std::string meta_json = src.meta_json();
    hdr.json_len = static_cast<uint32_t>(meta_json.size());

    const uint64_t logical = 4 * src.plane_size();
    const uint8_t* payload = src.raw_payload();  // non-null only for a raw (uncompressed) source
    if (payload) {
        // The source mapping stays valid for the whole call (TableReader is
        // borrowed, not moved), so `payload` is safe to read from throughout
        // -- including after the temp file is renamed over `path`, since the
        // source and destination are different files until that rename.
        SequentialPageReleaser releaser(payload, logical);
        write_block_compressed(path, hdr, meta_json, logical, block_size, level,
                               [&](uint64_t begin, size_t /*len*/) -> const uint8_t* {
                                   releaser.advance(begin);  // drop pages fully behind us
                                   return payload + begin;   // straight into the source mmap; no copy
                               });
    } else {
        // Re-blocking an already-compressed source: no flat payload to point
        // into, so stream through read_range instead, which decompresses
        // each covering source block through the reader's own bounded cache
        // (a few MB) rather than a decompress-to-disk round trip or
        // buffering the whole table.
        std::vector<uint8_t> scratch(block_size);
        write_block_compressed(path, hdr, meta_json, logical, block_size, level,
                               [&](uint64_t begin, size_t len) -> const uint8_t* {
                                   src.read_range(begin, len, scratch.data());
                                   return scratch.data();
                               });
    }
}

TableReader::TableReader(TableReader&& other) noexcept
    : base_(other.base_),
      map_size_(other.map_size_),
      ps_(other.ps_),
      json_len_(other.json_len_),
      block_size_(other.block_size_),
      nblocks_(other.nblocks_),
      offsets_(other.offsets_),
      blocks_(other.blocks_),
      cache_(std::move(other.cache_)) {
    other.reset();
}

TableReader& TableReader::operator=(TableReader&& other) noexcept {
    if (this != &other) {
        if (base_) munmap(const_cast<uint8_t*>(base_), map_size_);
        base_ = other.base_;
        map_size_ = other.map_size_;
        ps_ = other.ps_;
        json_len_ = other.json_len_;
        block_size_ = other.block_size_;
        nblocks_ = other.nblocks_;
        offsets_ = other.offsets_;
        blocks_ = other.blocks_;
        cache_ = std::move(other.cache_);
        other.reset();
    }
    return *this;
}

TableReader::~TableReader() {
    if (base_) munmap(const_cast<uint8_t*>(base_), map_size_);
}

void TableReader::reset() {
    base_ = nullptr;
    map_size_ = 0;
    ps_ = 0;
    json_len_ = 0;
    block_size_ = 0;
    nblocks_ = 0;
    offsets_ = nullptr;
    blocks_ = nullptr;
    cache_.reset();
}

std::optional<TableReader> TableReader::open(const std::string& path) {
    OpenError ignored = OpenError::None;
    return open(path, &ignored);
}

std::optional<TableReader> TableReader::open(const std::string& path, OpenError* err) {
    if (err) *err = OpenError::None;
    int fd = ::open(path.c_str(), O_RDONLY);
    if (fd < 0) {
        if (err) *err = OpenError::NotFound;
        return std::nullopt;
    }

    struct stat st{};
    if (fstat(fd, &st) != 0) {
        ::close(fd);
        if (err) *err = OpenError::NotFound;
        return std::nullopt;
    }
    size_t filesize = static_cast<size_t>(st.st_size);
    if (filesize < sizeof(TableHeader)) {
        ::close(fd);
        if (err) *err = OpenError::Unreadable;
        return std::nullopt;
    }

    void* mapped = mmap(nullptr, filesize, PROT_READ, MAP_SHARED, fd, 0);
    ::close(fd);  // fd not needed after mmap
    // Unreadable, not NotFound: open() and fstat() already succeeded, so the file
    // demonstrably exists. Reporting a mapping failure (ENOMEM, map-count limits,
    // an odd filesystem) as "missing" is the very confusion this overload exists
    // to prevent -- the caller would advise regenerating a table that is right there.
    if (mapped == MAP_FAILED) {
        if (err) *err = OpenError::Unreadable;
        return std::nullopt;
    }

    const uint8_t* base = static_cast<const uint8_t*>(mapped);
    const TableHeader* hdr = reinterpret_cast<const TableHeader*>(base);

    if (std::memcmp(hdr->magic, "HM8P", 4) != 0) {
        munmap(mapped, filesize);
        if (err) *err = OpenError::Unreadable;
        return std::nullopt;
    }

    // The magic is ours: the file IS a helpmate table. A version this build has never
    // heard of means it was written by a newer helpmate -- distinct from a malformed one.
    if (hdr->version > 3) {
        munmap(mapped, filesize);
        if (err) *err = OpenError::UnsupportedVersion;
        return std::nullopt;
    }

    // Validate without overflowable arithmetic: json_len and plane_size come from an
    // untrusted mmap'd header, and `4 * plane_size` can wrap mod 2^64 for crafted files.
    bool marker = (hdr->flags & kFlagAllUnsolvable) != 0;
    bool compressed = (hdr->version == 3);
    bool ok;
    if (compressed) {
        // block_size is retunable per file with no version bump, and the
        // reader sizes its decompressed-block cache off it (see
        // kBlockCacheBytes below) -- an absurd value from a crafted header
        // must be rejected here, not left to allocate on the first get().
        ok = !marker && hdr->encoding == kEncodingBlocks && hdr->codec == kCodecZstd && hdr->block_size > 0 &&
             hdr->block_size <= kMaxBlockSize;
    } else {
        ok = (hdr->version == 1 || (hdr->version == 2 && marker)) && hdr->encoding == kEncodingRaw;
    }
    if (ok) {
        uint64_t after_header =
            filesize - sizeof(TableHeader);  // filesize >= sizeof(TableHeader) already checked
        if (hdr->json_len > after_header) {
            ok = false;
        } else {
            uint64_t remaining = after_header - hdr->json_len;
            if (compressed) {
                // `4 * plane_size` can wrap mod 2^64 for a crafted header -- guard
                // before the multiply, same discipline as the raw path above.
                if (hdr->plane_size > (UINT64_MAX / 4)) {
                    ok = false;
                } else {
                    uint64_t logical = 4 * hdr->plane_size;
                    uint64_t nb = block_count(logical, hdr->block_size);
                    // Enough room for the count and its offsets, and the offsets
                    // must describe a payload that fits in what is left.
                    if (nb > (UINT64_MAX - 2) / sizeof(uint64_t)) {
                        ok = false;
                    } else {
                        uint64_t index_bytes = sizeof(uint64_t) * (nb + 2);
                        ok = remaining >= index_bytes;
                        if (ok) {
                            const uint8_t* idx = base + sizeof(TableHeader) + hdr->json_len;
                            uint64_t stated;
                            std::memcpy(&stated, idx, sizeof(stated));
                            ok = (stated == nb);
                            if (ok) {
                                // Raw bytes, not `const uint64_t*`: see load_u64's comment --
                                // this offset (idx + 8) depends on json_len and is not
                                // generally 8-byte aligned.
                                const uint8_t* offs = idx + sizeof(uint64_t);
                                const uint64_t payload_bytes = remaining - index_bytes;
                                ok = load_u64(offs + nb * sizeof(uint64_t)) <= payload_bytes;
                                // Interior offsets are untrusted too: get()/byte_at() index
                                // blocks_ + offs[b] .. blocks_ + offs[b+1] without further
                                // checking, so a single out-of-bounds or decreasing entry
                                // reads (or feeds zstd) arbitrary memory. This is an O(n_blocks)
                                // scan at open time -- one sequential pass over the whole index,
                                // once per open, against a file that can be tens of GB; do not
                                // "optimise" it away by trusting the final offset alone.
                                if (ok && load_u64(offs) != 0) ok = false;
                                if (ok) {
                                    for (uint64_t i = 0; ok && i < nb; ++i) {
                                        ok = load_u64(offs + i * sizeof(uint64_t)) <=
                                             load_u64(offs + (i + 1) * sizeof(uint64_t));
                                    }
                                }
                            }
                        }
                    }
                }
            } else {
                ok = marker ? (remaining == 0) : ((remaining % 4 == 0) && (hdr->plane_size == remaining / 4));
            }
        }
    }
    if (!ok) {
        munmap(mapped, filesize);
        if (err) *err = OpenError::Unreadable;
        return std::nullopt;
    }

    TableReader r;
    r.base_ = base;
    r.map_size_ = filesize;
    r.ps_ = hdr->plane_size;
    r.json_len_ = hdr->json_len;
    if (compressed) {
        const uint8_t* idx = base + sizeof(TableHeader) + hdr->json_len;
        std::memcpy(&r.nblocks_, idx, sizeof(r.nblocks_));
        r.offsets_ = idx + sizeof(uint64_t);  // raw bytes; see load_u64
        r.blocks_ = idx + sizeof(uint64_t) * (r.nblocks_ + 2);
        r.block_size_ = hdr->block_size;
        // Sized by a byte budget, not a fixed block count: block_size is
        // retunable per file (up to kMaxBlockSize, enforced above), so "64
        // blocks" is only 4 MB at the default 64 KB block_size -- at a
        // larger, still-legal block_size it would be tens or hundreds of MB.
        //
        // 4 MB was the original budget and it was far too small. The
        // enumeration path (mine --theme/--starts/--ends, which walks a
        // position's optimal solutions) probes cells at effectively random
        // indices, and its working set did not fit: `mine KRvkbn --dtm 8
        // --theme model --max 200` took 10.74s against 0.91s on the raw
        // table, because nearly every probe paid a full block decompression
        // to read one byte. 16 MB already reaches parity (0.99s); 64 MB
        // leaves headroom for larger materials. This budget is a ceiling,
        // not a reservation -- the LRU only ever allocates blocks actually
        // touched, and the run above peaked at 62 MB RSS in total.
        //
        // The ceiling is per TableReader, and a Tablebase holds one reader
        // per material in a closure, so the aggregate bound is the sum over
        // loaded slices of min(kBlockCacheBytes, that slice's logical size).
        // The min() is what keeps a closure of small sub-slice tables from
        // each claiming the full budget.
        constexpr size_t kBlockCacheBytes = 64 * 1024 * 1024;
        const uint64_t logical_bytes = 4 * hdr->plane_size;
        const size_t budget = static_cast<size_t>(std::min<uint64_t>(kBlockCacheBytes, logical_bytes));
        size_t capacity = std::max<size_t>(1, budget / hdr->block_size);
        r.cache_ = std::make_unique<BlockCache>(capacity, hdr->block_size);
    }
    return r;
}

ValuePair TableReader::get(Color stm, uint64_t cell) const {
    // Last line of defence: `cell` reaches here from a caller's index computation, and an
    // out-of-range value would otherwise read at base_ + <arbitrary offset> -- straight off
    // the end of the mapping, or (since the arithmetic wraps) anywhere at all.
    if (cell >= ps_)
        throw std::out_of_range("TableReader::get: cell " + std::to_string(cell) +
                                " out of range (plane size " + std::to_string(ps_) + ")");
    if (all_unsolvable()) return {DTM_UNSOLVABLE, 0};
    uint64_t o = (stm == Color::Black ? ps_ : 0) + cell;
    if (block_size_ == 0) {  // raw: unchanged
        const uint8_t* pay = base_ + sizeof(TableHeader) + json_len_;
        return {pay[o], pay[2 * ps_ + o]};
    }
    return {byte_at(o), byte_at(2 * ps_ + o)};
}

void TableReader::read_values(Color stm, uint64_t first_cell, size_t n, uint8_t* dtm, uint8_t* cnt) const {
    if (n == 0) return;
    // Same discipline as get()'s bounds check, and it has to happen before the
    // marker short-circuit below so an out-of-range span is an error on every
    // shape of table, not silently a plane full of DTM_UNSOLVABLE.
    if (first_cell > ps_ || n > ps_ - first_cell)
        throw std::out_of_range("TableReader::read_values: [" + std::to_string(first_cell) + ", " +
                                std::to_string(first_cell + n) + ") out of range (plane size " +
                                std::to_string(ps_) + ")");
    if (all_unsolvable()) {  // no payload exists to read; get() answers the same way
        std::memset(dtm, DTM_UNSOLVABLE, n);
        if (cnt) std::memset(cnt, 0, n);
        return;
    }
    const uint64_t o = (stm == Color::Black ? ps_ : 0) + first_cell;
    read_range(o, n, dtm);
    if (cnt) read_range(2 * ps_ + o, n, cnt);
}

size_t TableReader::cache_lookups() const { return cache_ ? cache_->hits() + cache_->fills() : 0; }

uint8_t TableReader::byte_at(uint64_t logical) const {
    const uint64_t b = logical / block_size_;
    const uint64_t begin = b * block_size_;
    const size_t offset = static_cast<size_t>(logical - begin);
    // Each thread keeps the last few blocks it read, so the common repeat
    // probe of a block skips the cache's shard mutex. A slot names a block by
    // (cache id, block index): ids are never reused and a cached block never
    // changes, so a slot cannot answer for the wrong table or stale bytes,
    // and its shared owner keeps the block alive after the cache evicts it.
    // get() reads a DTM byte and then its count byte 2 * ps_ further on, so
    // the two halves have separate banks: with one shared bank, any table
    // whose 2 * ps_ is a multiple of kLocalBlocks blocks (every five-piece
    // pawnless table at the default block size) mapped both reads to one
    // slot, and they evicted each other on every probe. A multiplicative hash
    // spreads the white and black planes of a half the same way. The cost is
    // up to 2 * kLocalBlocks blocks per thread beyond the cache's capacity
    // (1 MiB at the 64 KiB maximum block size).
    struct LocalBlock {
        uint64_t cache_id = 0;
        uint64_t index = 0;
        std::shared_ptr<const BlockCache::Block> data;
    };
    constexpr int kSlotBits = 3;
    constexpr size_t kLocalBlocks = size_t{1} << kSlotBits;
    thread_local std::array<std::array<LocalBlock, kLocalBlocks>, 2> local;
    const uint64_t id = cache_->id();
    constexpr uint64_t kGolden = 0x9E3779B97F4A7C15ull;
    LocalBlock& slot = local[logical >= 2 * ps_][((b + id * kGolden) * kGolden) >> (64 - kSlotBits)];
    if (slot.cache_id == id && slot.index == b) return (*slot.data)[offset];

    const size_t len = static_cast<size_t>(std::min<uint64_t>(block_size_, 4 * ps_ - begin));
    const uint64_t off_b = load_u64(offsets_ + b * sizeof(uint64_t));
    const uint64_t off_b1 = load_u64(offsets_ + (b + 1) * sizeof(uint64_t));
    const uint8_t* src = blocks_ + off_b;
    const size_t clen = static_cast<size_t>(off_b1 - off_b);
    slot.data = cache_->block(b, len, [&](uint8_t* dst, size_t n) { decompress_block(src, clen, dst, n); });
    slot.cache_id = id;
    slot.index = b;
    return (*slot.data)[offset];
}

void TableReader::read_range(uint64_t logical_offset, size_t len, uint8_t* dst) const {
    if (len == 0) return;
    const uint64_t total = 4 * ps_;
    // Same discipline as get()'s bounds check: `logical_offset`/`len` come
    // from a caller's own arithmetic (e.g. compress_existing streaming block
    // by block), and reading past the logical payload would otherwise read
    // off the end of the mapping or, since the addition can wrap, anywhere.
    if (logical_offset > total || len > total - logical_offset)
        throw std::out_of_range("TableReader::read_range: [" + std::to_string(logical_offset) + ", " +
                                std::to_string(logical_offset + len) + ") out of range (logical size " +
                                std::to_string(total) + ")");
    if (block_size_ == 0) {  // raw: one memcpy straight off the mapping
        const uint8_t* pay = base_ + sizeof(TableHeader) + json_len_;
        std::memcpy(dst, pay + logical_offset, len);
        return;
    }
    // Compressed: walk the blocks the range overlaps, decompressing each one
    // exactly once (per call) through this reader's own cache and copying
    // out only the overlapping span -- never a byte-at-a-time loop, which
    // would take the cache mutex len times instead of (at most) once per
    // block touched.
    uint64_t pos = logical_offset;
    size_t remaining = len;
    uint8_t* out = dst;
    while (remaining > 0) {
        const uint64_t b = pos / block_size_;
        const uint64_t begin = b * block_size_;
        const size_t block_len = static_cast<size_t>(std::min<uint64_t>(block_size_, total - begin));
        const size_t offset_in_block = static_cast<size_t>(pos - begin);
        const size_t take = std::min(remaining, block_len - offset_in_block);
        const uint64_t off_b = load_u64(offsets_ + b * sizeof(uint64_t));
        const uint64_t off_b1 = load_u64(offsets_ + (b + 1) * sizeof(uint64_t));
        const uint8_t* src = blocks_ + off_b;
        const size_t clen = static_cast<size_t>(off_b1 - off_b);
        cache_->read_range(b, offset_in_block, take, block_len, out,
                           [&](uint8_t* d, size_t n) { decompress_block(src, clen, d, n); });
        out += take;
        pos += take;
        remaining -= take;
    }
}

uint64_t TableReader::plane_size() const { return ps_; }

uint8_t TableReader::max_dtm() const { return reinterpret_cast<const TableHeader*>(base_)->max_dtm; }

std::string TableReader::material_name() const {
    const TableHeader* hdr = reinterpret_cast<const TableHeader*>(base_);
    return std::string(hdr->material, ::strnlen(hdr->material, sizeof(hdr->material)));
}

std::string TableReader::meta_json() const {
    return std::string(reinterpret_cast<const char*>(base_ + sizeof(TableHeader)), json_len_);
}

bool TableReader::all_unsolvable() const {
    return (reinterpret_cast<const TableHeader*>(base_)->flags & kFlagAllUnsolvable) != 0;
}

bool TableReader::is_compressed() const { return block_size_ != 0; }

uint32_t TableReader::block_size() const { return block_size_; }

const uint8_t* TableReader::raw_payload() const {
    if (block_size_ != 0) return nullptr;  // compressed: not a flat byte range
    if (all_unsolvable()) return nullptr;  // marker: no payload follows the header/JSON at all
    return base_ + sizeof(TableHeader) + json_len_;
}

}  // namespace hm
