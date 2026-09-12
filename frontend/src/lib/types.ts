export interface Me {
  id: string
  email: string
  display_name: string
  role: 'teacher' | 'student' | 'admin'
}

export interface Course {
  id: string
  title: string
  join_code: string
  teacher_id: string
  teacher_name: string
  archived: boolean
  created_at: string
  student_count: number
}

export interface CourseSummary {
  id: string
  title: string
  teacher_name: string
  student_count: number
}

export interface EnrolledStudent {
  id: string
  email: string
  display_name: string
  enrolled_at: string
}

export interface AnswerBox {
  id: string
  label: string
  points: number | null
  bbox: number[] | null
  page_index: number | null
}

export interface GroundTruthBox {
  id: string
  label: string
}

export interface Question {
  question_id: string
  course_id: string
  title: string | null
  state: 'draft' | 'finalized'
  physical_page: string
  dpi: number
  // A Tiptap/ProseMirror document.
  content: Record<string, unknown> | null
  answer_boxes: AnswerBox[]
  ground_truth_boxes: GroundTruthBox[]
  page_count: number | null
  created_at: string
  finalized_at: string | null
}

/** What the editor emits on change — the doc plus its boxes, indexed out. */
export interface QuestionDocPayload {
  content: Record<string, unknown>
  answer_boxes: { id: string; label: string; points: number | null }[]
  ground_truth_boxes: { id: string; label: string }[]
}

export interface AnswerGrade {
  answer_box_id: string
  label: string
  order_index: number
  max_score: number
  score: number | null
  llm_score: number | null
  override_score: number | null
  feedback: string | null
  llm_feedback: string | null
  override_feedback: string | null
  provider: string | null
  needs_manual_review: boolean
  review_reason: string | null
  model_answer_text: string | null
  model_answer_images: string[]
}

export interface SubmissionGrades {
  submission_id: string
  question_id: string
  student_id: string | null
  grading_status: 'ungraded' | 'queued' | 'grading' | 'graded' | 'failed'
  grading_error: string | null
  released: boolean
  earned: number
  max_score: number
  needs_review_count: number
  grades: AnswerGrade[]
}

export interface SubmissionSummary {
  id: string
  question_id: string
  student_id: string | null
  student_name: string | null
  modality: string
  created_at: string
  grading_status: SubmissionGrades['grading_status']
  released: boolean
  earned: number | null
  max_score: number | null
  needs_review_count: number | null
}

export interface AnswerPart {
  part: number
  page_index: number | null
  qr_check: 'pass' | 'fail' | 'absent' | null
  registration: 'local' | 'global' | null
  crop_url: string
}

export interface GroupedAnswerBox {
  answer_box_id: string
  label: string
  points: number | null
  order_index: number
  expected_parts: number
  parts: AnswerPart[]
  complete: boolean
}

export interface GroupedSubmission {
  submission_id: string
  question_id: string
  modality: string
  answer_boxes: GroupedAnswerBox[]
}

/** A model answer as rendered at finalize — what the grader is shown. */
export interface GroundTruthPreview {
  id: string
  label: string
  question_id: string
  /** Rendered image of the question this answers. */
  question_image_id: string | null
  /** Rendered image of the model answer itself. */
  image_id?: string
}

/** A paper as a student sees it — never carries document content. */
export interface StudentAssignment {
  question_id: string
  course_id: string
  title: string | null
  total_marks: number
  page_count: number | null
  finalized_at: string | null
  submission_id: string | null
  submission_status: SubmissionGrades['grading_status'] | null
  released: boolean
  earned: number | null
  max_score: number | null
}

export interface GradebookCell {
  question_id: string
  submission_id: string | null
  status: string
  released?: boolean
  earned?: number
  max?: number
  needs_review_count?: number
}

export interface GradebookRow {
  student_id: string
  display_name: string
  email: string
  cells: GradebookCell[]
}

export interface Gradebook {
  course_id: string
  questions: { id: string; title: string | null; state: string; created_at: string }[]
  rows: GradebookRow[]
}

export interface RubricSuggestion {
  id: string
  suggested_points: number
  rubric: string
}

export interface CorrectnessResult {
  ground_truth_box_id: string
  label: string
  index: number
  /** null when the check itself couldn't run. */
  ok: boolean | null
  issue: string | null
  explanation: string
  suggested_question: string | null
  suggested_answer: string | null
}
