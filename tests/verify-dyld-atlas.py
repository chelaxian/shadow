"""Exercise the real Atlas publication helper without an iOS runtime."""
import os
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / "src/ShadowCore.dylib/hooks/Universal/dyld.x").read_text()
start = source.index("static void shdw_dyld_publish_task_info_mirror(void) {")
end = source.index("\nstatic void shdw_dyld_mirror_restore_originals", start)
helper = source[start:end]
assert not re.search(
    r"_shdw_all_image_infos->compact_dyld_image_info_(?:addr|size)\s*=(?!=)",
    source,
), "dyld-owned Atlas fields must remain unchanged"

driver = r'''
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
typedef int BOOL;
#define YES 1
#define NO 0
#define KERN_SUCCESS 0
#define VM_FLAGS_ANYWHERE 1
#define NSLog(...) ((void)0)
typedef uintptr_t vm_address_t;
struct dyld_all_image_infos {
    unsigned version;
    unsigned infoArrayCount;
    const void *infoArray;
    uintptr_t compact_dyld_image_info_addr;
    size_t compact_dyld_image_info_size;
};
static struct dyld_all_image_infos *_shdw_all_image_infos;
static struct dyld_all_image_infos *_shdw_task_dyld_info_mirror;
static BOOL _shdw_task_dyld_info_mirror_alloc_failed;
static int fail_allocation;
static int mach_task_self(void) { return 1; }
static int vm_allocate(int task, vm_address_t *out, size_t size, int flags) {
    (void)task; (void)flags;
    if (fail_allocation) return 1;
    *out = (vm_address_t)calloc(1, size);
    return *out ? KERN_SUCCESS : 1;
}
'''
driver += helper
driver += r'''
int main(void) {
    struct dyld_all_image_infos native = {16, 123, (void *)0x1000, 0x2000, 1024};
    struct dyld_all_image_infos before = native;
    _shdw_all_image_infos = &native;
    shdw_dyld_publish_task_info_mirror();
    assert(memcmp(&native, &before, sizeof(native)) == 0);
    assert(_shdw_task_dyld_info_mirror != &native);
    assert(_shdw_task_dyld_info_mirror->infoArray == native.infoArray);
    assert(_shdw_task_dyld_info_mirror->infoArrayCount == 123);
    assert(_shdw_task_dyld_info_mirror->compact_dyld_image_info_addr == 0);
    assert(_shdw_task_dyld_info_mirror->compact_dyld_image_info_size == 0);
    native.version = 15;
    shdw_dyld_publish_task_info_mirror();
    assert(memcmp(_shdw_task_dyld_info_mirror, &native, sizeof(native)) == 0);
    free(_shdw_task_dyld_info_mirror);
    _shdw_task_dyld_info_mirror = NULL;
    fail_allocation = 1;
    shdw_dyld_publish_task_info_mirror();
    assert(_shdw_task_dyld_info_mirror_alloc_failed);
    assert(!_shdw_task_dyld_info_mirror);
    assert(native.compact_dyld_image_info_addr == 0x2000);
    return 0;
}
'''
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "atlas.c"
    binary = Path(tmp) / "atlas"
    path.write_text(driver)
    subprocess.run([os.environ.get("CC", "cc"), "-std=c99", "-Wall", "-Wextra",
                    "-Werror", str(path), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print("verify-dyld-atlas: native state, copied state, version and allocation checks passed")
