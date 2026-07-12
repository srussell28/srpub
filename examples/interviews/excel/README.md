Excel / Google-Sheets
============

This question is designed to be fairly flexible and open-ended,
allowing different candidates to focus on different areas, and
adjusting to different levels (intern, new-grad, senior).

## Question
Design a backend to support excel / google-sheets.

We should support set/get methods to store and retrieve cells.
The cell contents may be strings, numbers, formulas, or formulas referencing other cells.
For simplicity we will limit formulas to addition only

Example Use:

```
>>> sheet = MySheet()

>>> sheet.put("A1", "hello")
>>> sheet.get("A1")
hello

>>> sheet.put("B2", "5")
>>> sheet.get("B2")
5

>>> sheet.put("A3", "=2+2")
>>> sheet.get("A3")
4

>>> sheet.put("C3", "=B2+2")
>>> sheet.get("C3")
7
```

### Additional Clarification / Scope

* The question can be broken into two parts by making formulas with references "part 2"
* In Excel Columns are lettered ("A", "B", "C", ...), Rows are numbered (1, 2, 3, ...)
* Formulas (any string starting with `=` sign, should be evaluated).  For simplicity
  we will only support addition in formulas.
* The backend can operate as a class, and does not need to load/save data to disk.
  New sheets can be initialized as empty
* The backend should support at least a `put` and `get` operation.  All data will
  be sent as strings and should be returned as strings.
* We do not need to support any style formatting, or other unshown operations like row-summing

Common Questions
(You shouldn't necessarily give this information up-front, but most candidates will end up asking)

* <b>How many rows/columns should the sheet be?</b>  Infinite, or resizeable to arbitrary sizes.
  We should be able set cell `ZZZ99999` without it breaking.  If its easier you can start with a fixed size
* <b>Is the data sparse or dense?</b> Either/unknown
* <b>Can I use `eval` to calculate formulas?</b> Do you think that's wise?  What might be some risks of this?
* <b>What should a `get` on an empty cell return?</b>Null or empty-string
* <b>What should an invalid formulas do?</b>Throw an error/exception on set

#### Example Solution

See [part1.py](part1.py) in this folder for a solution that supports formulas but not references.

Some candidates will evaluate formulas on either the put or the get.
It doesn't really matter at this point, but will become important later.

#### Discussion
* The candidate should realize that a dict/hash-table is the best datastructure to use
  It's common to initially think of a array/list/2d-array since the sheet "looks"
  like a 2d-array, but once you realize that the data may be sparse, and that
  we want to support arbitrary sizes, the obvious memory-efficient O(1) solution
  is a dictionary.  If they choose any other datastructure, ask them about the
  memory-use or read/write access speed.
* For this part, they can get away without needing a `Cell` class
  by storing everything as a string.  Some un-typed languages (python)
  you can have a dict which stores arbitrary-mixed types, which is okay.
  There are many different solutions in different languages for storing
  different types of data which will become more relevant/necessary in later steps,
  but if they implement one here thats okay.

## Part 2
Extending the solution to support references to other cells in formulas.

Three example solutions are provided:

* [part2_simple.py](part2_simple.py) : A simpler but less efficient solution, which does
  redundant recursive calculation.
* [part2_efficient.py](part2_efficient.py) : A complex but more efficient solution which builds a
  graph of cell dependencies, and only re-calculates where needed
* [part2_hard_mode.py](part2_hard_mode.py) : Handles additional edge cases gracefully

Some candidates will on-their-own catch the extra implications that:

* Cells with formulas referencing other cells should update if the cell they
  reference is updated
* Referenced cells might be formulas themselves, so its necessary to support
  recursive evaluation or solve this another way.

I do not usually point this out, I wait to see how they implement part 2 given
only the first example.  If they don't catch this on their own, then I might
give them the extra test-cases below.

```
>>> sheet.set("B2", "10")
>>> sheet.get("C3")
12

>>> sheet.set("B2", "=10+10")
>>> sheet.get("C3")
22
```

Doing efficient evaluation is tricky here, because you need to keep track of
graph of relationships between cells, and only update cells when a cell they
depend on gets updated.   The lazy solution is functionally correct, but
would incur significant cost if there are larger graphs of cell dependencies.

A nice middle-ground some candidates find is lazy evaluation with caching:
cache each computed value, and on put just walk the dependents marking them
dirty rather than recomputing them.  Gets only recompute dirty cells, so
writes stay cheap and repeated reads don't redo work.

Strong candidates may also ask (or should be asked) about circular references
(`A1="=B1"`, `B1="=A1"`).  Ideally these are detected and rejected with an
error on put; the lazy solution will hit infinite recursion.  See
[part2_hard_mode.py](part2_hard_mode.py) for a solution handling this, along
with other edge cases like forward references to cells that don't exist yet.

## Possible Extensions

* Implement your solution as a web-service (like in Google-Sheets) that can support
  multiple concurrent editors. (Reference solution in [part3.py](part3.py) )
* Implement efficient saving-to-disk and loading-to-disk
