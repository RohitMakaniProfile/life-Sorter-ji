import { createContext, useContext, useState, useEffect } from 'react';

const ThemeContext = createContext();

export const useTheme = () => {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useTheme must be used within ThemeProvider');
  }
  return context;
};

export const ThemeProvider = ({ children }) => {
  const [theme] = useState('light');

  useEffect(() => {
    // Apply theme to document
    document.documentElement.setAttribute('data-theme', theme);

    // Clear any old dark preference
    localStorage.setItem('ikshan-theme', theme);
  }, [theme]);

  const toggleTheme = () => {};

  const value = {
    theme,
    toggleTheme,
    isDark: false,
    isBlue: false,
    isGreen: false
  };

  return (
    <ThemeContext.Provider value={value}>
      {children}
    </ThemeContext.Provider>
  );
};
