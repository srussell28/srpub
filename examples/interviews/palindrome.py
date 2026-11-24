# given a string, return all palindromes
#  "kayak" => ["k", "a", "y", "a", "k", "aya", "kayak"]
# "panna" => ["p", "a", "n", "n", "a", "nn", "anna"]


def is_palindrome(s):
    i = 0
    j = len(s) - 1
    while i < j:
        if s[i] != s[j]:
            return False
        i += 1
        j -= 1
    return True


def palindrome_brute(s):
    print(f"===== palindrome_brute {s} === ")
    results = []
    for seq_length in range(1, len(s) + 1):  # n
        print("seq_length", seq_length)
        for start in range(len(s)):  # n
            end = start + seq_length
            if end > len(s):
                continue
            substr = s[start:end]
            match = is_palindrome(substr)  # n
            print(start, "->", end, ":", substr, match)
            if match:
                results.append(substr)
    return results


print(palindrome_brute("kayak"))
print(palindrome_brute("panna"))


def palindrome_better(s):
    print(f"===== palindrome_better {s} === ")
    mid = 0
    results = []
    for mid in range(len(s)):  # N
        # Check for odd-length palindromes centered on a the letter mid
        print(mid, s[mid])
        seq_length = 0
        while True:  # N
            start = mid - seq_length
            end = mid + seq_length
            if start < 0 or end >= len(s):
                break
            if s[start] == s[end]:
                # this is a palindrome
                results.append(s[start : end + 1])
                seq_length += 1
            else:
                break
        # Check for even-lenght palindromes centered at mid + 0.5
        mid_half = mid + 0.5
        seq_length = 0.5
        while True:
            start = int(mid_half - seq_length)
            end = int(mid_half + seq_length)
            if start < 0 or end >= len(s):
                break
            if s[start] == s[end]:
                # this is a palindrome
                results.append(s[start : end + 1])
                seq_length += 1
            else:
                break

    return results


print(palindrome_better("kayak"))
print(palindrome_better("panna"))
