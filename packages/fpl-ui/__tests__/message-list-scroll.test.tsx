/**
 * @jest-environment jsdom
 */
import { render } from '@testing-library/react';
import MessageList, { type Message } from '../components/chat/MessageList';

const scrollToMock = jest.fn();
const scrollIntoViewMock = jest.fn();

Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
  configurable: true,
  value: scrollToMock,
});

Object.defineProperty(Element.prototype, 'scrollIntoView', {
  configurable: true,
  value: scrollIntoViewMock,
});

describe('MessageList autoscroll', () => {
  beforeEach(() => {
    scrollToMock.mockClear();
    scrollIntoViewMock.mockClear();
  });

  it('scrolls only the message viewport when messages change', () => {
    const messages: Message[] = [
      { id: 'user-1', role: 'user', text: '@xg' },
    ];

    const { container, rerender } = render(
      <MessageList messages={messages} loading={false} />,
    );
    const messageViewport = container.firstElementChild;

    expect(scrollToMock).toHaveBeenCalledWith({
      top: expect.any(Number),
      behavior: 'smooth',
    });
    expect(scrollToMock.mock.instances[0]).toBe(messageViewport);
    expect(scrollIntoViewMock).not.toHaveBeenCalled();

    rerender(
      <MessageList
        messages={[
          ...messages,
          { id: 'assistant-1', role: 'assistant', text: 'Respuesta' },
        ]}
        loading={false}
      />,
    );

    expect(scrollToMock.mock.instances.at(-1)).toBe(messageViewport);
    expect(scrollIntoViewMock).not.toHaveBeenCalled();
  });
});
