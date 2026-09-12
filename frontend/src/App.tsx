import { AuthenticatedTemplate, UnauthenticatedTemplate } from '@azure/msal-react'
import { Route, Routes } from 'react-router-dom'

import { AppLayout } from './components/AppLayout'
import { CourseDetailPage } from './pages/CourseDetailPage'
import { CoursesPage } from './pages/CoursesPage'
import { GradebookPage } from './pages/GradebookPage'
import { LoginPage } from './pages/LoginPage'
import { QuestionEditorPage } from './pages/QuestionEditorPage'
import { SearchPage } from './pages/SearchPage'
import { StudentResultPage } from './pages/StudentResultPage'
import { SubmissionReviewPage } from './pages/SubmissionReviewPage'
import { Toaster } from '@/components/ui/sonner'

function App() {
  return (
    <>
      <AuthenticatedTemplate>
        <Routes>
          <Route element={<AppLayout />}>
            <Route path="/" element={<CoursesPage />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/courses/:courseId" element={<CourseDetailPage />} />
            <Route path="/courses/:courseId/gradebook" element={<GradebookPage />} />
            <Route path="/questions/:questionId" element={<QuestionEditorPage />} />
            <Route path="/submissions/:submissionId" element={<SubmissionReviewPage />} />
            <Route path="/results/:submissionId" element={<StudentResultPage />} />
          </Route>
        </Routes>
      </AuthenticatedTemplate>
      <UnauthenticatedTemplate>
        <Routes>
          <Route path="*" element={<LoginPage />} />
        </Routes>
      </UnauthenticatedTemplate>
      <Toaster />
    </>
  )
}

export default App
