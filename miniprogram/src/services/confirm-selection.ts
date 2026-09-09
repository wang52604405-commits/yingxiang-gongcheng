import { selectionStorage } from '@/stores/selection'
import type { Assignment, MatchCandidate, UploadDraft } from '@/types/domain'

/** A picker result belongs only to the page action that requested it. */
export function createConfirmSelectionSession() {
  let request: { owner: string; project: string } | null = null
  return {
    begin(project: string) {
      request = { owner: selectionStorage.getOwner(), project }
      selectionStorage.clearConfirmDestination(project)
    },
    consume(project: string) {
      const pending = request
      request = null
      if (!pending || pending.owner !== selectionStorage.getOwner() || pending.project !== project) return null
      const value = selectionStorage.getConfirmDestination(project)
      selectionStorage.clearConfirmDestination(project)
      return value
    },
  }
}

export function initialConfirmAssignment(draft: UploadDraft, candidate?: MatchCandidate): Assignment | undefined {
  const baseline = draft.assignment
  if (draft.assignment_explicit && baseline) return { ...baseline }
  if (!candidate) return baseline ? { ...baseline } : undefined
  const sameDestination = baseline && (draft.scope === 'engineering'
    ? Boolean(candidate.unit_code && candidate.unit_code === baseline.unit_code)
    : Boolean(candidate.other_node_code && candidate.other_node_code === baseline.other_node_code))
  return sameDestination ? { ...baseline, process_name: candidate.process_name || baseline.process_name } : {
    unit_code: candidate.unit_code, unit_name: candidate.unit_name, process_name: candidate.process_name,
    other_node_code: candidate.other_node_code, other_node_name: candidate.other_node_name,
  }
}
