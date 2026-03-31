import IkshanApp from './components/ikshan/IkshanApp';
import ErrorBoundary from './components/ErrorBoundary';

function App() {
  return (
    <ErrorBoundary>
      <IkshanApp />
    </ErrorBoundary>
  );
}

export default App;
