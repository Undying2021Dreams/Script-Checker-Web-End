import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiFetch } from './api'
import type {
  CorrectnessResult,
  Course,
  Gradebook,
  CourseSummary,
  Leaderboard,
  EnrolledStudent,
  Me,
  GroundTruthPreview,
  JoinRequestOut,
  NotificationList,
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
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: QuestionDocPayload) =>
      apiFetch<Question>(`/questions/${questionId}/blocks`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      }),
    // The saved answer boxes are what the marks summary counts, and it
    // used to keep showing whatever they were worth when the page was
    // opened — a paper edited to 42 still read "3 marks" until reload.
    //
    // Written into the cache rather than refetched, so the document the
    // teacher is typing into is never replaced underneath them.
    onSuccess: (saved) => {
      qc.setQueryData<Question>(['question', questionId], (prev) =>
        prev
          ? {
              ...prev,
              answer_boxes: saved.answer_boxes,
              ground_truth_boxes: saved.ground_truth_boxes,
            }
          : saved,
      )
      qc.invalidateQueries({ queryKey: ['suggested-marks', questionId] })
    },
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

export function useDeleteQuestion(questionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () =>
      apiFetch<{ deleted: string; submissions_deleted: number; marks_deleted: number }>(
        `/questions/${questionId}`,
        { method: 'DELETE' },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['questions'] }),
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
    mutationFn: ({
      answerBoxId,
      score,
      feedbackDoc,
    }: {
      answerBoxId: string
      score: number | null
      // The server flattens this into the plain-text feedback itself,
      // so a client sends the document and nothing else.
      feedbackDoc?: Record<string, unknown> | null
    }) =>
      apiFetch<SubmissionGrades>(`/submissions/${submissionId}/grades/${answerBoxId}`, {
        method: 'PATCH',
        body: JSON.stringify({ score, feedback_doc: feedbackDoc ?? null }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['grades', submissionId] }),
  })
}

export function useSetAnswerBoxMarks(questionId: string, submissionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ answerBoxId, points }: { answerBoxId: string; points: number }) =>
      apiFetch<{ id: string; points: number }>(
        `/questions/${questionId}/answer-boxes/${answerBoxId}`,
        { method: 'PATCH', body: JSON.stringify({ points }) },
      ),
    // The marks belong to the question, so the answer list carries them,
    // while the totals a mark is shown against come from the grades.
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['answers', submissionId] })
      qc.invalidateQueries({ queryKey: ['grades', submissionId] })
    },
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

export function useReleaseAll(questionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (released: boolean) =>
      apiFetch<{ changed: number; skipped: number }>(`/questions/${questionId}/release-all`, {
        method: 'POST',
        body: JSON.stringify({ released }),
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

export function useDeleteSubmission(questionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (submissionId: string) =>
      apiFetch<{ deleted: string }>(`/submissions/${submissionId}`, { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['submissions', questionId] })
      // A student's own view of the paper counts their submission, so it
      // has to hear about this too.
      qc.invalidateQueries({ queryKey: ['assignments'] })
    },
  })
}


export function useOverrideGrades(submissionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (
      grades: {
        answer_box_id: string
        score: number | null
        feedback_doc: Record<string, unknown> | null
      }[],
    ) =>
      apiFetch<SubmissionGrades>(`/submissions/${submissionId}/grades`, {
        method: 'PATCH',
        body: JSON.stringify({ grades }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['grades', submissionId] })
      qc.invalidateQueries({ queryKey: ['submissions'] })
    },
  })
}

export function useResetMarks(submissionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () =>
      apiFetch<SubmissionGrades>(`/submissions/${submissionId}/reset-marks`, { method: 'POST' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['grades', submissionId] })
      qc.invalidateQueries({ queryKey: ['submissions'] })
    },
  })
}

export function useResetAllMarks(questionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () =>
      apiFetch<{ changed: number; skipped: number }>(
        `/questions/${questionId}/reset-all-marks`,
        { method: 'POST' },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['submissions', questionId] })
      qc.invalidateQueries({ queryKey: ['grades'] })
    },
  })
}


export function useNotifications() {
  return useQuery({
    queryKey: ['notifications'],
    queryFn: () => apiFetch<NotificationList>('/notifications'),
    // The bell is the one thing on screen that is about events rather
    // than state, so it is the one thing worth asking about on a timer.
    refetchInterval: 60_000,
  })
}

export function useMarkNotificationsRead() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (notificationId?: string) =>
      apiFetch<NotificationList>(
        `/notifications/read${notificationId ? `?notification_id=${notificationId}` : ''}`,
        { method: 'POST' },
      ),
    onSuccess: (data) => qc.setQueryData(['notifications'], data),
  })
}

export function useUpdateProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { display_name?: string; institution?: string }) =>
      apiFetch<Me>('/me', { method: 'PATCH', body: JSON.stringify(body) }),
    onSuccess: (me) => qc.setQueryData(['me'], me),
  })
}

export function useSetAvatar() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData()
      form.append('image', file)
      return apiFetch<Me>('/me/avatar', { method: 'POST', body: form })
    },
    onSuccess: (me) => qc.setQueryData(['me'], me),
  })
}

export function useRequestToJoin() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (courseId: string) =>
      apiFetch<{ status: string }>(`/courses/${courseId}/request-join`, { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['course-search'] }),
  })
}

export function useJoinRequests(courseId: string, enabled: boolean) {
  return useQuery({
    queryKey: ['join-requests', courseId],
    queryFn: () => apiFetch<JoinRequestOut[]>(`/courses/${courseId}/join-requests`),
    enabled,
  })
}

export function useDecideJoinRequest(courseId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ requestId, approve }: { requestId: string; approve: boolean }) =>
      apiFetch<JoinRequestOut>(
        `/courses/${courseId}/join-requests/${requestId}?approve=${approve}`,
        { method: 'POST' },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['join-requests', courseId] })
      qc.invalidateQueries({ queryKey: ['course', courseId] })
      qc.invalidateQueries({ queryKey: ['students', courseId] })
    },
  })
}


export function useUploadSubmission(questionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      file,
      modality,
      submissionId,
      pageIndex,
      pageIndexHint,
    }: {
      file: File
      modality: string
      submissionId?: string
      // Only when the student names the page themselves, because its
      // printed codes could not be read. Sending it otherwise would
      // override what the page says about itself — and replace that
      // page rather than adding one.
      pageIndex?: number
      // What the student said as they took the photograph. The server
      // uses it only if the codes cannot be read, so it costs nothing
      // when they can and saves a round trip when they cannot.
      pageIndexHint?: number
    }) => {
      const form = new FormData()
      form.append('question_id', questionId)
      form.append('modality', modality)
      form.append('image', file)
      if (submissionId) form.append('submission_id', submissionId)
      if (pageIndex !== undefined) form.append('page_index', String(pageIndex))
      if (pageIndexHint !== undefined) form.append('page_index_hint', String(pageIndexHint))
      return apiFetch<{ submission_id: string; pages: unknown[] }>('/submissions', {
        method: 'POST',
        body: form,
      })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['submissions', questionId] })
      // The submission page lists what has arrived so far, and the
      // assignment row counts it. Without these, adding a second page
      // uploaded it perfectly well and then showed nothing: the first
      // page appeared only because setting the submission id started
      // that query for the first time.
      qc.invalidateQueries({ queryKey: ['submission-pages'] })
      qc.invalidateQueries({ queryKey: ['assignments'] })
    },
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

export function useLeaderboard(courseId: string, enabled = true) {
  return useQuery({
    enabled,
    queryKey: ['leaderboard', courseId],
    queryFn: () => apiFetch<Leaderboard>(`/courses/${courseId}/leaderboard`),
  })
}

export function usePopularCourses() {
  return useQuery({
    queryKey: ['popular-courses'],
    queryFn: () => apiFetch<CourseSummary[]>('/courses/popular'),
  })
}

// ── Assembling a script ─────────────────────────────────────────────

export interface SubmissionPage {
  page_index: number
  markers_detected?: string
  crops?: unknown[]
  error?: string | null
}

export function useSubmissionPages(submissionId: string | null) {
  return useQuery({
    enabled: !!submissionId,
    queryKey: ['submission-pages', submissionId],
    queryFn: () =>
      apiFetch<{ pages: SubmissionPage[] }>(`/submissions/${submissionId}`),
  })
}

export function useDeleteSubmissionPage(submissionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (pageIndex: number) =>
      apiFetch<{ pages: SubmissionPage[] }>(
        `/submissions/${submissionId}/pages/${pageIndex}`,
        { method: 'DELETE' },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['submission-pages', submissionId] })
      qc.invalidateQueries({ queryKey: ['assignments'] })
    },
  })
}

export function useHandInSubmission(submissionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () =>
      apiFetch<{ submitted_at: string }>(`/submissions/${submissionId}/submit`, {
        method: 'POST',
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['submission-pages', submissionId] })
      qc.invalidateQueries({ queryKey: ['assignments'] })
    },
  })
}

export interface SuggestedMark {
  answer_box_id: string
  label: string
  points: number | null
  // What the marking scheme looks like it adds up to. A suggestion: it
  // used to be applied silently and got real schemes wrong in ways only
  // visible after a mark had been given.
  suggested: number | null
}

export function useSuggestedMarks(questionId: string, enabled: boolean) {
  return useQuery({
    enabled,
    queryKey: ['suggested-marks', questionId],
    queryFn: () => apiFetch<SuggestedMark[]>(`/questions/${questionId}/suggested-marks`),
  })
}

export function useSetPaperTotal(questionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (total: number | null) =>
      apiFetch<Question>(`/questions/${questionId}`, {
        method: 'PATCH',
        body: JSON.stringify({ total_marks_declared: total }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['question', questionId] }),
  })
}
