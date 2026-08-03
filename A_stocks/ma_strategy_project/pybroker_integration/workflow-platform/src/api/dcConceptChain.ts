import {
  buildVpSixComboSymbolsFile,
  DC_CONCEPT_MEMBERS_CSV,
  extractSymbolsFromMembersCsv,
  filterStockCodes,
  VP_SIX_COMBO_SYMBOLS_PATH,
} from '@/api/filterStockCodes'
import { fetchWorkspaceFile, saveWorkspaceFile } from '@/api/workflow'

export type DcConceptChainResult = {
  ok: boolean
  message: string
  outputCount: number
  inputCount: number
  dupSkipped: number
  prefixSkipped: number
}

/**
 * fetch_dc_concept_ma5 成功后：
 * members.csv → 股票清洗 → config/fetch_vp_six_combo_symbols.txt
 */
export async function chainDcConceptToVpSixCombo(): Promise<DcConceptChainResult> {
  const file = await fetchWorkspaceFile(DC_CONCEPT_MEMBERS_CSV)
  if (!file.exists || !file.content.trim()) {
    return {
      ok: false,
      message: `未找到 ${DC_CONCEPT_MEMBERS_CSV}，跳过自动清洗`,
      outputCount: 0,
      inputCount: 0,
      dupSkipped: 0,
      prefixSkipped: 0,
    }
  }

  const raw = extractSymbolsFromMembersCsv(file.content)
  const filtered = filterStockCodes(raw.join('\n'))
  const body = buildVpSixComboSymbolsFile(filtered.codes)
  const saved = await saveWorkspaceFile(VP_SIX_COMBO_SYMBOLS_PATH, body)

  if (!saved) {
    return {
      ok: false,
      message: `清洗完成但写入 ${VP_SIX_COMBO_SYMBOLS_PATH} 失败`,
      outputCount: filtered.outputCount,
      inputCount: filtered.inputCount,
      dupSkipped: filtered.dupSkipped,
      prefixSkipped: filtered.prefixSkipped,
    }
  }

  return {
    ok: true,
    message: `已清洗并写入 ${VP_SIX_COMBO_SYMBOLS_PATH}（有效 ${filtered.inputCount} · 去重 ${filtered.dupSkipped} · 剔除 ${filtered.prefixSkipped} · 输出 ${filtered.outputCount}）`,
    outputCount: filtered.outputCount,
    inputCount: filtered.inputCount,
    dupSkipped: filtered.dupSkipped,
    prefixSkipped: filtered.prefixSkipped,
  }
}
