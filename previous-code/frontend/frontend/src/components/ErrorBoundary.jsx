import { Component } from 'react';

/**
 * Error Boundary Component
 * Catches JavaScript errors anywhere in the child component tree,
 * logs those errors, and displays a fallback UI.
 */
class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { 
      hasError: false,
      error: null,
      errorInfo: null
    };
  }

  static getDerivedStateFromError(error) {
    // Update state so the next render will show the fallback UI
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    // Log error to console in development
    if (process.env.NODE_ENV === 'development') {
      console.error('ErrorBoundary caught an error:', error, errorInfo);
    }
    
    this.setState({ errorInfo });
    
    // You can also log the error to an error reporting service here
    // logErrorToService(error, errorInfo);
  }

  handleReload = () => {
    window.location.reload();
  };

  handleReset = () => {
    this.setState({ 
      hasError: false, 
      error: null, 
      errorInfo: null 
    });
  };

  render() {
    if (this.state.hasError) {
      // Custom fallback UI
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div style={styles.container}>
          <div style={styles.content}>
            <div style={styles.icon}>⚠️</div>
            <h1 style={styles.title}>Something went wrong</h1>
            <p style={styles.message}>
              We're sorry, but something unexpected happened. 
              Please try refreshing the page.
            </p>
            
            {process.env.NODE_ENV === 'development' && this.state.error && (
              <details style={styles.details}>
                <summary style={styles.summary}>Error Details</summary>
                <pre style={styles.errorText}>
                  {this.state.error.toString()}
                  {this.state.errorInfo?.componentStack}
                </pre>
              </details>
            )}
            
            <div style={styles.buttonGroup}>
              <button 
                onClick={this.handleReset} 
                style={styles.secondaryButton}
              >
                Try Again
              </button>
              <button 
                onClick={this.handleReload} 
                style={styles.primaryButton}
              >
                Refresh Page
              </button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

const styles = {
  container: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: '100vh',
    backgroundColor: '#0f0f0f',
    padding: '20px',
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
  },
  content: {
    textAlign: 'center',
    maxWidth: '500px',
    padding: '40px',
    backgroundColor: '#1a1a1a',
    borderRadius: '16px',
    border: '1px solid #333',
  },
  icon: {
    fontSize: '64px',
    marginBottom: '20px',
  },
  title: {
    color: '#ffffff',
    fontSize: '24px',
    fontWeight: '600',
    marginBottom: '12px',
  },
  message: {
    color: '#a0a0a0',
    fontSize: '16px',
    lineHeight: '1.6',
    marginBottom: '24px',
  },
  details: {
    textAlign: 'left',
    marginBottom: '24px',
    backgroundColor: '#252525',
    borderRadius: '8px',
    padding: '12px',
  },
  summary: {
    color: '#ff6b6b',
    cursor: 'pointer',
    fontWeight: '500',
    marginBottom: '8px',
  },
  errorText: {
    color: '#ff6b6b',
    fontSize: '12px',
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
    maxHeight: '200px',
    overflow: 'auto',
    margin: '8px 0 0 0',
  },
  buttonGroup: {
    display: 'flex',
    gap: '12px',
    justifyContent: 'center',
  },
  primaryButton: {
    backgroundColor: '#6366f1',
    color: '#ffffff',
    border: 'none',
    padding: '12px 24px',
    borderRadius: '8px',
    fontSize: '16px',
    fontWeight: '500',
    cursor: 'pointer',
    transition: 'background-color 0.2s',
  },
  secondaryButton: {
    backgroundColor: 'transparent',
    color: '#a0a0a0',
    border: '1px solid #333',
    padding: '12px 24px',
    borderRadius: '8px',
    fontSize: '16px',
    fontWeight: '500',
    cursor: 'pointer',
    transition: 'all 0.2s',
  },
};

export default ErrorBoundary;
