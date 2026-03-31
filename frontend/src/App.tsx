import { BrowserRouter } from 'react-router-dom';
import IkshanApp from './components/ikshan/IkshanApp';
import ErrorBoundary from './components/ErrorBoundary';

function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <IkshanApp />
      </BrowserRouter>
    </ErrorBoundary>
  );
}

export default App;
