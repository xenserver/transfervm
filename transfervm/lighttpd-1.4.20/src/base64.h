#ifndef _BASE64_H_
#define _BASE64_H_

int b64_ntop(u_char const *src, size_t srclength, char *target, size_t targsize);
int b64_pton(char const *src, u_char *target, size_t targsize);

#endif // _BASE64_H_
