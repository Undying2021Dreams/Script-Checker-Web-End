import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiFetch } from './api'
import type {
  CorrectnessResult,
  Course,
  Gradebook,
  CourseSummary,
  EnrolledStudent,
  Me,
  GroundTruthPreview,
  GroupedSubmission,
  Question,
  QuestionDocPayload,
  RubricSuggestion,
  SubmissionGrades,
  StudentAssignment,
  SubmissionSummary,
} from './types'

export function useMe() {
  return useQuery({ queryKey: ['me'], queryFn: () => apiFetch<Me>('/me') })
}

export function useMyCourses() {
  return useQuery({ queryKey: ['courses'], queryFn: () => apiFetch<Course[]>('/courses') })
}

export function useCourse(courseId: string) {
  return useQuery({
    queryKey: ['course', courseId],
    queryFn: () => apiFetch<Course>(`/courses/${courseId}`),
  })
}

export function useRoster(courseId: string, enabled: boolean) {
  return useQuery({
    queryKey: ['roster', courseId],
    queryFn: () => apiFetch<EnrolledStudent[]>(`/courses/${courseId}/students`),
    enabled,
  })
}

export function useCourseSearch(term: string) {
  return useQuery({
    queryKey: ['course-search', term],
    queryFn: () =>
      apiFetch<CourseSummary[]>(`/courses/search?q=${encodeURIComponent(term)}`),
    enabled: term.trim().length > 0,
  })
}

export function useCreateCourse() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (title: string) =>
      apiFetch<Course>('/courses', { method: 'POST', body: JSON.stringify({ title }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['courses'] }),
  })
}

export function useJoinCourse() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (joinCode: string) =>
      apiFetch<Course>('/courses/join', {
        method: 'POST',
        body: JSON.stringify({ join_code: joinCode }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['courses'] }),
  })
}

export function useRemoveStudent(courseId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (studentId: string) =>
      apiFetch<void>(`/courses/${courseId}/students/${studentId}`, { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['roster', courseId] })
      qc.invalidateQueries({ queryKey: ['course', courseId] })
    },
  })
}

// ── Questions ───────────────────────────────────────────────────────

export function useCourseQuestions(courseId: string) {
  return useQuery({
    queryKey: ['questions', courseId],
    queryFn: () => apiFetch<Question[]>(`/questions?course_id=${courseId}`),
  })
}

export function useQuestion(questionId: string) {
  return useQuery({
    queryKey: ['question', questionId],
    queryFn: () => apiFetch<Question>(`/questions/${questionId}`),
  })
}

export function useCreateQuestion(courseId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () =>
      apiFetch<Question>(`/questions?course_id=${courseId}`, {
        method: 'POST',
        body: JSON.stringify({}),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['questions', courseId] }),
  })
}

export function useSaveQuestion(questionId: string) {
  return useMutation({
    mutationFn: (payload: QuestionDocPayload) =>
      apiFetch<Question>(`/questions/${questionId}/blocks`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      }),
  })
}

export function useRenameQuestion(questionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (title: string) =>
      apiFetch<Question>(`/questions/${questionId}`, {
        method: 'PATCH',
        body: JSON.stringify({ title }),
      }),
    onSuccess: (q) => {
      qc.invalidateQueries({ queryKey: ['question', questionId] })
      qc.invalidateQueries({ queryKey: ['questions', q.course_id] })
    },
  })
}

export function useCloneQuestion(questionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => apiFetch<Question>(`/questions/${questionId}/clone`, { method: 'POST' }),
    onSuccess: (q) => qc.invalidateQueries({ queryKey: ['questions', q.course_id] }),
  })
}

export function useFinalizeQuestion(questionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () =>
      apiFetch<Question>(`/questions/${questionId}/finalize`, { method: 'POST' }),
    onSuccess: (q) => {
      qc.invalidateQueries({ queryKey: ['question', questionId] })
      qc.invalidateQueries({ queryKey: ['questions', q.course_id] })
    },
  })
}

// ── Grading ─────────────────────────────────────────────────────────

export function useSubmissionGrades(submissionId: string, enabled = true) {
  return useQuery({
    enabled,
    queryKey: ['grades', submissionId],
    queryFn: () => apiFetch<SubmissionGrades>(`/submissions/${submissionId}/grades`),
    // Grading runs in the background, so keep polling while a run is in
    // flight and stop once it settles — the caller shouldn't have to
    // track that itself.
    refetchInterval: (query) => {
      const status = query.state.data?.grading_status
      return status === 'queued' || status === 'grading' ? 2000 : false
    },
  })
}

export function useRunGrading(submissionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (provider: string) =>
      apiFetch<SubmissionGrades>(`/submissions/${submissionId}/grade`, {
        method: 'POST',
        body: JSON.stringify({ provider }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['grades', submissionId] }),
  })
}

export function useOverrideGrade(submissionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ answerBoxId, score, feedback }: { answerBoxId: string; score: number | null; feedback?: string }) =>
      apiFetch<SubmissionGrades>(`/submissions/${submissionId}/grades/${answerBoxId}`, {
        method: 'PATCH',
        body: JSON.stringify({ score, feedback }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['grades', submissionId] }),
  })
}

export function useReleaseGrades(submissionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (release: boolean) =>
      apiFetch<SubmissionGrades>(
        `/submissions/${submissionId}/${release ? 'release' : 'unrelease'}`,
        { method: 'POST' },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['grades', submissionId] }),
  })
}

// ── Submissions ─────────────────────────────────────────────────────

export function useSubmissions(questionId: string) {
  return useQuery({
    queryKey: ['submissions', questionId],
    queryFn: () => apiFetch<SubmissionSummary[]>(`/submissions?question_id=${questionId}`),
    // A batch run marks submissions one after another, so keep refreshing
    // while any are still in flight and stop once they've all settled.
    refetchInterval: (query) =>
      query.state.data?.some(
        (s) => s.grading_status === 'queued' || s.grading_status === 'grading',
      )
        ? 2500
        : false,
  })
}

export function useGradeAll(questionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ provider, includeGraded }: { provider: string; includeGraded: boolean }) =>
      apiFetch<{ queued: number; skipped: number }>(`/questions/${questionId}/grade-all`, {
        method: 'POST',
        body: JSON.stringify({ provider, include_graded: includeGraded }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['submissions', questionId] }),
  })
}

export function useSubmissionAnswers(submissionId: string) {
  return useQuery({
    queryKey: ['answers', submissionId],
    queryFn: () => apiFetch<GroupedSubmission>(`/submissions/${submissionId}/answers`),
  })
}

export function useUploadSubmission(questionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ file, modality, submissionId }: { file: File; modality: string; submissionId?: string }) => {
      const form = new FormData()
      form.append('question_id', questionId)
      form.append('modality', modality)
      form.append('image', file)
      if (submissionId) form.append('submission_id', submissionId)
      return apiFetch<{ submission_id: string; pages: unknown[] }>('/submissions', {
        method: 'POST',
        body: form,
      })
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['submissions', questionId] }),
  })
}

export function useGroundTruthPreviews(questionId: string, enabled: boolean) {
  return useQuery({
    queryKey: ['ground-truth', questionId],
    queryFn: () => apiFetch<GroundTruthPreview[]>(`/questions/${questionId}/ground-truth`),
    enabled,
  })
}

// ── Student ─────────────────────────────────────────────────────────

export function useAssignments(courseId: string, enabled: boolean) {
  return useQuery({
    queryKey: ['assignments', courseId],
    queryFn: () => apiFetch<StudentAssignment[]>(`/student/assignments?course_id=${courseId}`),
    enabled,
  })
}

export function useGradebook(courseId: string, enabled: boolean) {
  return useQuery({
    queryKey: ['gradebook', courseId],
    queryFn: () => apiFetch<Gradebook>(`/courses/${courseId}/gradebook`),
    enabled,
  })
}

// ── Authoring helpers ───────────────────────────────────────────────

export function useSuggestRubric(questionId: string) {
  return useMutation({
    mutationFn: (provider: string) =>
      apiFetch<{ suggestions: RubricSuggestion[] }>(`/questions/${questionId}/suggest-rubric`, {
        method: 'POST',
        body: JSON.stringify({ provider }),
      }),
  })
}

export function useCheckAnswerKey(questionId: string) {
  return useMutation({
    // groundTruthBoxId scopes the check to one sub-question; omitted, the
    // whole paper is checked.
    mutationFn: ({ provider, groundTruthBoxId }: { provider: string; groundTruthBoxId?: string }) =>
      apiFetch<{ results: CorrectnessResult[] }>(`/questions/${questionId}/check-correctness`, {
        method: 'POST',
        body: JSON.stringify({ provider, ground_truth_box_id: groundTruthBoxId ?? null }),
      }),
  })
}
