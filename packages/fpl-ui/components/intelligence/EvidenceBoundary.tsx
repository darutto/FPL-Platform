'use client';

import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  failed: boolean;
}

export default class EvidenceBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(_error: Error, _info: ErrorInfo): void {
    // Evidence failures are contained without logging potentially sensitive payloads.
  }

  render(): ReactNode {
    if (this.state.failed) return null;
    return this.props.children;
  }
}
