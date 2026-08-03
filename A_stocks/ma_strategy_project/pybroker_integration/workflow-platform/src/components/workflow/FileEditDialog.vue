<script setup lang="ts">
import { ref, watch } from 'vue'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { fetchWorkspaceFile, saveWorkspaceFile } from '@/api/workflow'

const open = defineModel<boolean>('open', { default: false })
const props = defineProps<{ path: string; label: string }>()

const content = ref('')
const loading = ref(false)
const saving = ref(false)
const message = ref('')

watch(
  () => [open.value, props.path] as const,
  async ([isOpen, path]) => {
    if (!isOpen || !path) return
    loading.value = true
    message.value = ''
    const data = await fetchWorkspaceFile(path)
    content.value = data.content
    loading.value = false
    if (!data.exists) message.value = '文件不存在，保存将新建。'
  },
)

async function onSave() {
  saving.value = true
  const ok = await saveWorkspaceFile(props.path, content.value)
  saving.value = false
  message.value = ok ? '已保存' : '保存失败（请确认后端已启动）'
  if (ok) open.value = false
}
</script>

<template>
  <Dialog :open="open" @update:open="(v) => (open = v)">
    <DialogContent class="max-w-2xl">
      <DialogHeader>
        <DialogTitle>编辑 · {{ label }}</DialogTitle>
        <DialogDescription class="font-mono text-xs">{{ path }}</DialogDescription>
      </DialogHeader>
      <textarea
        v-model="content"
        :disabled="loading"
        class="min-h-64 w-full rounded-md border bg-muted/30 p-3 font-mono text-xs leading-relaxed outline-none focus:border-ring"
        spellcheck="false"
      />
      <p v-if="message" class="text-xs text-muted-foreground">{{ message }}</p>
      <DialogFooter>
        <Button variant="outline" @click="open = false">关闭</Button>
        <Button :disabled="saving || loading" @click="onSave">保存</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
